# Concevoir un workflow

Le framework ne s'occupe que de la mécanique : comment tourne une étape, comment se raccordent les sessions, que faire en cas d'échec, comment économiser le contexte.
**Le [workflow](../reference/glossary.md#流程), c'est vous qui l'écrivez** — le framework ne sait pas sur quel projet vous travaillez ni dans quel langage,
et il n'a pas à le savoir. Cette page explique comment concevoir un workflow ; le tableau complet des champs de `Step` et `Workflow` est dans la
[Python API](../reference/api.md).

## Quel problème ça résout {#解决什么问题}

Un run [long-horizon](../reference/glossary.md#长程) ne tient pas dans une seule phrase de prompt : d'abord clarifier le besoin,
puis enquêter, puis implémenter, puis relire — chaque segment a son rôle, son contexte, ses conditions d'acceptation.
Si vous mettez tout dans un seul prompt, le modèle décidera lui-même quel segment sauter ; écrit sous forme de workflow, **l'ordre, les conditions de sortie et le passage d'état deviennent du code
Python** — lisible, testable, et vous pouvez ne rejouer que l'étape cassée.

`Workflow` ne fait que trois choses :

- exécuter une suite d'[étapes](../reference/glossary.md#步骤) dans l'ordre
- décider ce que chaque étape voit de ce qui précède (trois modes de raccordement des sessions + un dictionnaire `ctx`)
- décider quand réessayer et quand sortir plus tôt

Il ne contient aucune hypothèse métier. Où découper, ce que chaque étape doit valider, que faire quand ça ne passe pas — ces quatre questions, c'est ça « concevoir un workflow ».

## Comment l'utiliser (code minimal) {#怎么用最小代码}

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # Nouvelle session : ne mange que ce qu'on lui passe dans le prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Toujours une nouvelle session, on injecte la sortie de l'étape précédente dans le prompt (pas cher, évite la pollution)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

L'argument de `flower run` est `module:attribut` ou `chemin/fichier:attribut`. Si l'objet récupéré est appelable, il est d'abord appelé une fois,
puis le `Workflow` obtenu est exécuté ; à la fin, le terminal affiche le coût total et le chemin du manifeste du run.

Vous pouvez aussi écrire votre propre programme pilote : le premier argument de `Workflow.run` est un `Runtime` :

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Ce qu'il fait réellement {#它实际做了什么}

### Ce qu'une Step reçoit, ce qu'elle doit renvoyer {#一个-step-收到什么必须返回什么}

`Step` n'est pas une fonction, c'est une **déclaration**. Ce qui s'exécute réellement, c'est `Runtime.run(step.spec, prompt rendu, ...)` —
**une étape = un `Runtime.run` = une [session](../reference/glossary.md#会话)**.

Les trois premiers champs sont positionnels, `Step(name, spec, prompt)` :

- `name` — le nom de l'étape. C'est en même temps la clé dans `ctx`, le nom de ligne dans `runs/manifest.json`,
  et la clé du [lignage](../reference/glossary.md#血缘) inter-processus.
- `spec` — avec quel `AgentSpec` exécuter. Il détermine la liste blanche d'outils, le modèle et le budget de cette étape.
- `prompt` — un `str`, ou un `(ctx) -> str`. Quand c'est appelable, il reçoit le `ctx` courant ;
  **c'est la façon la moins chère d'injecter la sortie de l'étape précédente** (l'autre étant de raccorder la session, voir plus bas).

Ce que l'étape « renvoie » est un `StepResult`, mais dans le workflow vous récupérez deux choses :

- `ctx[step.name]` — par défaut `result.text`, remplacé par la valeur de retour de `reduce` si vous en donnez un ;
- `ctx["_results"][step.name]` — le `StepResult` complet (coût, nombre de tours, nombre de tentatives, `session_id`).

`result.text` **ne collecte que le corps du thread principal** : les prises de parole d'un subagent restent dans son propre transcript, le
[brief de tâche](../reference/glossary.md#任务书) qui lui est confié est `kind="prompt"`, l'erreur synthétique d'une déconnexion est `kind="error"`
— aucun des trois n'y entre.

### reduce : ce n'est pas du sucre {#reduce不是糖}

Par défaut, ce qui est transmis vers l'aval, c'est la parole brute du modèle. Pour certaines étapes, cette parole brute **ne doit pas** être transmise telle quelle :

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

En pratique, l'étape de clarification du besoin **colle tout le code source** en plus des quatre sections. Ce qui part vers l'aval doit être les quatre sections parsées,
sinon tout ce code entre dans le prompt de l'étape suivante. C'est ce champ qui rattrape le coup dans `clarify_step`.

`reduce` **doit être une fonction synchrone** ; `gate` / `when` / `on_reject` peuvent être async.

### Comment l'état circule dans ctx {#状态怎么在-ctx-里流动}

`ctx` est un `dict[str, Any]`, c'est `Workflow.context` lui-même. Après chaque étape, l'écriture suit ce tableau :

| Cas | `ctx[nom_étape]` | Le reste |
|---|---|---|
| `when(ctx)` renvoie False | **non écrit**, l'étape entière est sautée | pas de result produit, rien dans `_results` |
| Passe | `reduce(result, ctx)`, ou `result.text` si absent | |
| Échec + `on_fail="stop"` (défaut) | **non écrit** | écrit `ctx["_failed_at"]`, tout le workflow s'arrête à cette étape |
| Échec + `on_fail="skip"` | **non écrit** | continue vers l'aval |
| Échec + `on_fail="continue"` | `result.text` (partiel, **sans passer par `reduce`**) | continue vers l'aval |

Que ça passe ou non, `ctx["_results"][nom_étape]` est toujours écrit ; si `result.session_id` est non vide, il est aussi écrit dans
`ctx["_sessions"]` et enregistré dans le lignage.

**Pour savoir si le workflow a réussi, regardez `ctx.get("_failed_at")`**, pas si la dernière étape a produit une sortie.

Toutes les clés commençant par un underscore sont posées par `Workflow.run` lui-même : `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — ne les utilisez pas comme noms d'étape. Chaque mécanisme pose aussi les siennes
(`_brief` / `_goal` / `_verdict`, etc.) ; la liste complète est dans la [Python API](../reference/api.md).

Parmi elles, `_runtime` et `_on_event` sont là pour les `gate` : un gate peut dépêcher lui-même un agent pour rendre un verdict,
et ce processus de verdict s'affiche quand même dans l'UI — sinon l'interface reste noire une dizaine de secondes et donne l'impression d'être bloquée.
C'est exactement comme ça qu'est implémenté le [gardien d'objectif](goal.md).

`ctx` est un seul et même dict : **si vous relancez le même objet `Workflow` une deuxième fois, les clés du run précédent sont toujours là**.
Pour repartir propre, créez-en un nouveau, ou passez explicitement `context={}`.

!!! warning "Avec on_fail=skip, `ctx[nom_étape]` n'est pas écrit"
    Un `lambda ctx: ctx["某步"]` en aval lèvera directement un `KeyError`. Pour continuer avec un résultat partiel, utilisez
    `on_fail="continue"` ; si vous voulez vraiment sauter, l'aval doit se protéger lui-même avec `ctx.get(...)`.

### Verdict et renvoi : gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` juge « ça a fini de tourner, mais est-ce conforme ». Deux détails à connaître absolument :

- **Quand `result.ok` est faux, `gate` n'est tout simplement pas appelé** (court-circuit).
- **Il n'est appelé qu'une fois par tentative**, la conclusion est conservée pour la suite — car il peut avoir des effets de bord. Le gate de `clarify_step` écrit le
  [brief](../reference/glossary.md#需求确认书) sur disque ; le déclencher deux fois écrit deux fois.

Ce qui se passe après un gate refusé dépend de la présence ou non d'un `on_reject` :

| | Comment tourne le tour suivant | Nom dans le manifest |
|---|---|---|
| `retries` seul | Reprise depuis le début, prompt d'origine, `resume_from` d'origine | `X#retry1` |
| Avec `on_reject` | **Poursuite de la session qui vient d'être refusée**, le prompt devient la valeur de retour de `on_reject`, `fork` forcé à False | `X#round2` |

Le second, c'est « je te renvoie ça, voilà ce qui manque, continue de le compléter » — le travail déjà fait et le contexte sont toujours là.
Si `on_reject` renvoie une chaîne vide, ou si cette tentative n'a jamais obtenu de `session_id`, on retombe sur une reprise depuis le début.

`gate` peut aussi lever `StepAbort`, ce qui veut dire **réessayer ne servira à rien, ne consommez pas les tours restants** :

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Après la levée : la raison est enregistrée dans `ctx["_aborted"]`, l'étape est traitée comme un échec et passe par `on_fail` (défaut `"stop"`),
**la boucle de retry casse sur-le-champ**, et pas un seul des `retries` restants n'est consommé.

Retenez bien la différence : **renvoyer False, c'est « raté cette fois, on refait un tour » ; `StepAbort`, c'est « refaire ne changera rien ».**
Le cas typique : l'objectif est jugé infaisable dans cet environnement et il n'y a personne à qui demander — continuer à tourner à vide est l'option la plus chère.

### Ne confondez pas les deux niveaux de retry {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Couvre quoi | Échec métier : `gate` refusé, `result.ok` faux | Infrastructure : réseau instable, coupure, 5xx |
| Comment on reprend | **Toute l'étape est refaite**, même prompt et même `resume_from` | **Reprise en resume depuis le point d'interruption**, le coût déjà payé n'est pas perdu |
| En attendant | Rien | Une sonde DNS + TCP attend le retour du réseau (aucun HTTP, aucune credential : la sonde doit être gratuite) |
| Non réessayable | — | Credential invalide, paramètre invalide : arrêt immédiat, pas d'attente inutile |

Le prompt utilisé pour la reprise **ne contient volontairement aucun détail d'erreur** — le modèle a besoin de savoir « tu as été interrompu, continue »,
pas de savoir si c'était un ENOTFOUND ou un 503.

### Enchaîner les étapes {#把步骤串起来}

Il y a trois façons de raccorder l'état d'une étape à l'autre ; le choix détermine ce que l'étape suivante peut voir :

| Écriture | Ce que voit l'étape suivante | Où l'utiliser |
|---|---|---|
| `resume_from=None` (défaut) + injection dans le prompt | Seulement les mots que vous injectez | Étapes indépendantes. Pas cher, évite la pollution |
| `resume_from="nom_étape_précédente"` | L'historique complet de la session | Quand il faut une mémoire continue |
| `resume_from="nom_étape_précédente"` + `fork=True` | L'historique complet, mais sur une nouvelle branche | Relecture / plusieurs pistes en parallèle / retry sans salir la ligne d'origine |

L'étape visée par `resume_from` **doit réellement avoir produit une session**. Si elle a été sautée par `when`, ou n'a tout simplement pas tourné,
`Workflow.run` lève directement une `ValueError` — pas de dégradation silencieuse vers une nouvelle session, car cela ferait tomber l'hypothèse
« mémoire continue » en douce.

Quelques leçons de conception payées cher, plusieurs fois :

1. **Une étape, un objectif vérifiable.** La frontière d'étape est la frontière de contexte : là où il y a `resume_from=None`,
   tous les résultats d'outils précédents cessent définitivement de résider en contexte. Voir [Économie du contexte](context.md).
2. **Dans le doute, commencez par `clarify_step`.** En long-horizon, « avoir mal compris l'objectif » est l'erreur la plus chère,
   et c'est précisément le genre d'erreur que les couches d'économie de contexte ne peuvent pas nettoyer. Voir [Clarification préalable](clarify.md).
3. **Une tâche déléguée doit se suffire à elle-même.** Un subagent part d'un contexte propre, il ne sait pas ce que sait le [coordinateur](../reference/glossary.md#协调者).
   Écrivez le contexte nécessaire dans le brief de tâche, ou dites-lui quel artefact aller lire.
4. **Les sorties longues passent par le disque, pas par la réponse.** C'est déjà écrit dans `WORKER_RULES` ; que vos `instructions` n'annulent pas cette règle
   (« colle-moi le log complet dans ta réponse »).
5. **Le `gate` doit d'abord vérifier des conditions dures.** Le fichier existe-t-il, le code de sortie vaut-il 0 : ce qui se juge en une ligne de Python ne se délègue pas à un modèle.
   Si vous voulez vraiment un jugement de modèle, utilisez `with_goal` qui existe déjà — il remplace le gate par une implémentation qui lance un
   [juge](../reference/glossary.md#判定者) indépendant ; ne bricolez pas votre propre version dans le gate.
6. **Pour modifier le même dépôt en parallèle, utilisez `worker(isolate=True)`.** La finalisation (merge, nettoyage des worktrees, ouverture de PR) reste pour l'instant à la charge de
   votre workflow ; le harness garantit seulement que les modifications atterrissent chacune dans son propre worktree.

### Le workbench doit être accroché au Workflow {#工作台要挂在-workflow-上}

Dès que le workflow doit écrire des fichiers dans le [workbench](../reference/glossary.md#工作台) — typiquement
`clarify_step(brief_path=...)` — vous devez créer vous-même un `Workbench` et l'accrocher **à la fois** à `Workflow.workbench`
et le passer au `Runtime` :

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

Accrocher `channel` au workflow a deux raisons : `run()` branche son `on_event` sur la même sortie d'événements
(uniquement si `channel.on_event` vaut encore `None`), et le programme pilote se sert de ce champ pour savoir à qui répondre.

!!! warning "Construire soi-même le chemin du workbench échoue silencieusement"
    L'emplacement par défaut de `Runtime(workbench=True)` est `<run_dir>/workbench`, alors que celui de `Workbench(ws)` est
    `<ws>/.flower` — **ce ne sont pas le même répertoire**. Quand le workflow est appelé par la CLI, il ne voit pas `run_dir` ; construire le chemin
    soi-même ne fait que pointer ailleurs, si bien que le brief est écrit dans le répertoire A pendant que l'index injecté scanne le répertoire B, **et sans aucune erreur**.
    Créez un seul objet partagé des deux côtés et le problème disparaît ; quand `Workflow.workbench` existe, le `-W` de la ligne de commande est ignoré,
    c'est lui qui fait foi.

### `continuous=True` : refaire tourner le même chemin {#continuoustrue同一个路径再跑一次}

Les trois modes de raccordement ci-dessus concernent les étapes **à l'intérieur d'un run**. L'inter-processus est un autre axe :

```python
Workflow([...], continuous=True)     # valeur par défaut
```

Relancé dans le même workspace, chaque étape reprend la parole dans la session du run précédent — grâce à la table
« nom d'étape → session_id » de `<run_dir>/lineage.json`. Au chargement, chaque entrée passe par `runtime.has_session()` pour vérifier que la session est encore en base,
et n'est utilisée que si elle est vivante : le fichier de lignage peut survivre à `sessions.db`, et faire un resume sur une session inexistante n'explose qu'une fois le sous-processus démarré.

Trois conséquences :

- **`resume_from=None` ne veut pas dire « session neuve ».** C'est vrai au premier run, pas au second. Pour avoir une session neuve à chaque fois,
  écrivez explicitement `Workflow(..., continuous=False)`.
- **En [continuité](../reference/glossary.md#接续), le contexte ne fait que grossir.** Si vous voulez dire autre chose lors de la reprise, donnez un
  `Step.resume_prompt` — ce que l'autre a déjà dans son contexte n'a pas à être renvoyé.
- Les étapes qui déclarent explicitement `resume_from` ne sont pas concernées : il est prioritaire.

!!! warning "Le nom d'étape est la clé inter-processus"
    Renommer une étape revient à couper son lignage : le run suivant ne reprend plus, et **sans aucune erreur**. Les noms de retry suffixés `#retry1` /
    `#round2` **n'entrent pas dans le lignage** (c'est toujours le nom d'origine qui est enregistré) ; c'est aussi une des façons d'implémenter « le juge est toujours une nouvelle session ».

Conception complète et `--new` dans [Continuité](continuity.md).

## Quand ne pas l'utiliser {#什么时候不该用它}

- **Un seul agent à lancer, et pas besoin de verdict** — n'enveloppez pas ça dans un `Workflow`. Faites directement `await rt.run(spec, "…")`,
  ou en ligne de commande `flower once "读一眼这个仓库"`.
- **La forme est exactement « clarifier le besoin → fixer l'objectif → travailler »** — utilisez le
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) existant,
  pas la peine de l'écrire vous-même :

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Ce sont **trois étapes** : `确认需求` → `设定目标` → `干活` (avec boucle de verdict, l'étape de verdict s'appelle `干活·判定#N`).
    Avec `goal=False`, il n'y a ni deuxième étape ni boucle de verdict ; avec `clarify_only=True`, seule la première subsiste.
    Il embarque son propre `HumanChannel` et son `Workbench` et les accroche au workflow, donc
    `Runtime(workbench=wf.workbench)` se prend tel quel, n'en fabriquez pas un autre.

    Sans écrire de code non plus : dans le répertoire du projet, `flower "帮我做一个 X"` lance exactement ça.
    **Ce n'est pas « la conception de workflow recommandée »**, c'est juste de quoi démarrer sans aucune configuration.

- **Des étapes découpées plus fin qu'« un objectif vérifiable »** — perte nette. Chaque étape ouvre une nouvelle session,
  et une nouvelle session a un plancher de démarrage (environ 34k de contexte mesuré pour le coordinateur) qu'on n'amortit pas.
- **Vouloir revenir après coup à un message précis** — le chemin `Workflow` ne le permet pas, il ne passe jamais `resume_at`.
  Appelez directement `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`.

Le choix des rôles (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) et la sémantique champ par champ de `Step` et `Workflow` sont dans la
[Python API](../reference/api.md) ; les termes sont dans le [glossaire](../reference/glossary.md).
