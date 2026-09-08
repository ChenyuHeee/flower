# Concevoir un workflow

Le framework ne s'occupe que de la mécanique : comment une étape s'exécute, comment les sessions
s'enchaînent, que faire en cas d'échec, comment économiser le contexte.
**Le [workflow](../reference/glossary.md#流程), c'est vous qui l'écrivez** — le framework ne sait pas
sur quel projet vous travaillez ni dans quel langage, et il n'a pas à le savoir. Cette page explique
comment concevoir un workflow ; le tableau complet des champs de `Step` et `Workflow` est dans
[l'API Python](../reference/api.md).

## Le problème résolu {#解决什么问题}

Une exécution [long-horizon](../reference/glossary.md#长程) ne tient pas dans un seul prompt :
d'abord clarifier le besoin, puis enquêter, puis implémenter, puis relire — chaque segment a son
rôle, son contexte, ses critères de recette. Tout écrire dans un seul prompt, et le modèle décidera
lui-même quel segment sauter ; l'écrire comme un workflow, et **l'ordre, les conditions de sortie et
le passage d'état deviennent du code Python** — lisible, testable, et permettant de ne relancer que
l'étape cassée.

`Workflow` ne fait que trois choses :

- exécuter une suite d'[étapes](../reference/glossary.md#步骤) dans l'ordre ;
- décider de ce que chaque étape voit des précédentes (trois modes d'enchaînement de session + un
  dictionnaire `ctx`) ;
- décider quand réessayer et quand sortir plus tôt.

Il ne contient aucune hypothèse métier. Où découper, ce que chaque étape doit valider, que faire en
cas de refus — ces quatre choses, c'est cela « concevoir un workflow ».

## Comment s'en servir (code minimal) {#怎么用最小代码}

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
        # Nouvelle session : ne voit que ce qui est passé dans le prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Nouvelle session également, on injecte la sortie de l'étape précédente dans le prompt
        # (économique, et protège de la pollution)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

L'argument de `flower run` est `module:attribut` ou `chemin_de_fichier:attribut`. Si l'objet obtenu
est appelable, il est appelé une fois pour récupérer le `Workflow`, puis exécuté ; à la fin, le
terminal affiche le coût total et le chemin du manifeste d'exécution.

Écrire son propre programme pilote fonctionne aussi ; le premier argument de `Workflow.run` est un
`Runtime` :

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Ce qu'il fait réellement {#它实际做了什么}

### Ce qu'une Step reçoit, ce qu'elle doit renvoyer {#一个-step-收到什么必须返回什么}

`Step` n'est pas une fonction, c'est une **déclaration**. Ce qui s'exécute vraiment, c'est
`Runtime.run(step.spec, prompt rendu, ...)` — **une étape = un appel à `Runtime.run` = une
[session](../reference/glossary.md#会话)**.

Les trois premiers champs sont positionnels, `Step(name, spec, prompt)` :

- `name` — le nom de l'étape. C'est en même temps la clé dans `ctx`, le nom de ligne dans
  `runs/manifest.json`, et la clé de la [lignée](../reference/glossary.md#血缘) inter-processus.
- `spec` — quel `AgentSpec` exécuter. Il détermine la liste blanche d'outils, le modèle et le budget
  de cette étape.
- `prompt` — un `str`, ou un `(ctx) -> str`. S'il est appelable, il reçoit le `ctx` courant ;
  **c'est la façon la moins chère de faire entrer la sortie de l'étape précédente** (l'autre étant
  d'enchaîner la session, voir plus bas).

Ce que l'étape « renvoie » est un `StepResult`, mais dans le workflow vous récupérez deux choses :

- `ctx[step.name]` — par défaut `result.text` ; si `reduce` est fourni, la valeur de retour de
  `reduce` ;
- `ctx["_results"][step.name]` — le `StepResult` complet (coût, nombre de tours, nombre de
  tentatives, `session_id`).

`result.text` **ne collecte que le corps du texte du main thread** : les prises de parole d'un
subagent sont dans son propre transcript, le [task brief](../reference/glossary.md#任务书) qui lui
est confié est de `kind="prompt"`, et l'erreur synthétique d'une coupure réseau est de
`kind="error"` — aucun des trois n'y entre.

### reduce : ce n'est pas du sucre {#reduce不是糖}

Par défaut, ce qui est transmis en aval, ce sont les mots exacts du modèle. Pour certaines étapes,
ces mots exacts **ne doivent pas** être transmis tels quels :

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

À l'usage, l'étape de clarification **recolle tout le code** en plus des quatre sections. Ce qui
part en aval doit être les quatre sections analysées, sinon tout ce code se retrouve dans le prompt
de l'étape suivante. `clarify_step` s'appuie précisément sur ce champ pour l'éviter.

`reduce` **doit être une fonction synchrone** ; `gate` / `when` / `on_reject` peuvent être async.

### Comment l'état circule dans ctx {#状态怎么在-ctx-里流动}

`ctx` est un `dict[str, Any]` — c'est `Workflow.context` lui-même. Après chaque étape, l'écriture
suit ce tableau :

| Cas | `ctx[nom de l'étape]` | Reste |
|---|---|---|
| `when(ctx)` renvoie False | **rien n'est écrit**, l'étape entière est sautée | aucun result produit, rien dans `_results` |
| Réussite | `reduce(result, ctx)`, ou `result.text` si absent | |
| Échec + `on_fail="stop"` (défaut) | **rien n'est écrit** | écrit `ctx["_failed_at"]`, le workflow s'arrête à cette étape |
| Échec + `on_fail="skip"` | **rien n'est écrit** | continue en aval |
| Échec + `on_fail="continue"` | `result.text` (partiel, **sans passer par `reduce`**) | continue en aval |

Réussite ou non, `ctx["_results"][nom de l'étape]` est toujours écrit ; si `result.session_id` est
non vide, il est aussi écrit dans `ctx["_sessions"]` et enregistré dans la lignée.

**Pour savoir si le workflow a réussi, regardez `ctx.get("_failed_at")`**, pas si la dernière étape a
produit une sortie.

Les clés commençant par un underscore sont posées par `Workflow.run` lui-même : `_runtime`,
`_on_event`, `_sessions`, `_results`, `_lineage`, `_woke`, `_aborted`, `_failed_at` — ne les prenez
pas comme noms d'étape. Chaque mécanisme pose aussi les siennes (`_brief` / `_goal` / `_verdict`,
etc.) ; la liste complète est dans [l'API Python](../reference/api.md).

Parmi elles, `_runtime` et `_on_event` sont destinées au `gate` : un gate peut dépêcher lui-même un
agent pour rendre un verdict, et ce verdict continue de s'afficher dans l'UI — sinon l'interface
reste noire une dizaine de secondes et donne l'impression d'être bloquée. C'est ainsi qu'est
implémenté le [goal guard](goal.md).

`ctx` est le même dict : **si vous relancez le même objet `Workflow` une seconde fois, les clés de la
première fois sont toujours là**. Pour repartir proprement, créez-en un nouveau, ou passez
explicitement `context={}`.

!!! warning "Avec on_fail=\"skip\", `ctx[nom de l'étape]` n'est pas écrit"
    Un `lambda ctx: ctx["une_étape"]` en aval lèvera directement un `KeyError`. Pour continuer avec
    un résultat partiel, utilisez `on_fail="continue"` ; si vous voulez vraiment sauter, l'aval doit
    se protéger lui-même avec `ctx.get(...)`.

### Verdict et renvoi : gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` juge « ça a tourné jusqu'au bout, mais est-ce conforme ? ». Deux détails
indispensables :

- **si `result.ok` est faux, `gate` n'est tout simplement pas appelé** (court-circuit) ;
- **il n'est appelé qu'une fois par tentative**, la conclusion étant conservée pour la suite — il
  peut avoir des effets de bord. Le gate de `clarify_step` écrit le
  [brief](../reference/glossary.md#需求确认书) sur disque ; le redéclencher, c'est réécrire le
  fichier.

Ce qui se passe après un gate refusé dépend de la présence ou non de `on_reject` :

| | Comment tourne le tour suivant | Nom dans le manifeste |
|---|---|---|
| `retries` seul | reprise depuis le début, prompt d'origine, `resume_from` d'origine | `X#retry1` |
| Avec `on_reject` | **poursuite de la session qui vient d'être refusée**, le prompt est remplacé par la valeur de retour de `on_reject`, `fork` forcé à False | `X#round2` |

Le second cas, c'est « on te renvoie ça, voilà ce qui manque, continue à compléter » — le travail
déjà fait et le contexte sont conservés. Si `on_reject` renvoie une chaîne vide, ou si cette
tentative n'a jamais obtenu de `session_id`, on retombe sur une reprise depuis le début.

`gate` peut aussi lever `StepAbort`, ce qui signifie **réessayer ne servira à rien, ne consommez pas
les tours restants** :

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Après la levée : la raison est enregistrée dans `ctx["_aborted"]`, l'étape est traitée comme un échec
et passe par `on_fail` (par défaut `"stop"`), la **boucle de retry est interrompue sur-le-champ**, et
aucun des `retries` restants n'est consommé.

À retenir : **renvoyer False signifie « pas cette fois, on refait un tour » ; `StepAbort` signifie
« refaire ne changera rien ».** Le cas typique est un objectif jugé irréalisable dans cet
environnement, sans personne à qui demander — continuer à tourner à vide est l'option la plus chère.

### Ne confondez pas les deux niveaux de retry {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Couvre quoi | échecs métier : `gate` refusé, `result.ok` faux | l'infrastructure : réseau instable, coupure, 5xx |
| Comment on reprend | **l'étape entière est refaite**, même prompt et même `resume_from` | **resume au point d'interruption**, le coût déjà dépensé n'est pas perdu |
| Que fait-on entre-temps | rien | des sondes DNS + TCP attendent le retour du réseau (pas de HTTP, pas de credentials — la sonde doit être gratuite) |
| Non réessayable | — | credentials invalides, paramètres invalides : arrêt immédiat, pas d'attente indéfinie |

Le prompt utilisé pour la reprise **ne contient volontairement aucun détail d'erreur** — le modèle a
besoin de savoir « tu as été interrompu, continue », pas de savoir si c'était un ENOTFOUND ou un 503.

### Enchaîner les étapes {#把步骤串起来}

Il existe trois façons de faire passer l'état d'une étape à l'autre ; le choix détermine ce que
l'étape suivante voit :

| Écriture | Ce que voit l'étape suivante | Où l'utiliser |
|---|---|---|
| `resume_from=None` (défaut) + injection dans le prompt | uniquement les mots que vous injectez | étapes indépendantes. Économique, protège de la pollution |
| `resume_from="nom de l'étape précédente"` | l'historique complet de la session | quand il faut une mémoire continue |
| `resume_from="nom de l'étape précédente"` + `fork=True` | l'historique complet, mais sur une branche séparée | relecture / plusieurs pistes en parallèle / retry sans salir la ligne d'origine |

L'étape désignée par `resume_from` **doit avoir réellement produit une session**. Si elle a été
sautée par `when`, ou n'a tout simplement pas tourné, `Workflow.run` lève directement une
`ValueError` — pas de dégradation silencieuse vers une nouvelle session, car cela invaliderait en
douce l'hypothèse de « mémoire continue ».

Quelques principes de conception payés cher :

1. **Une étape, un objectif recevable.** La frontière d'étape est la frontière de contexte : là où
   `resume_from=None`, tous les résultats d'outils précédents cessent définitivement de résider en
   contexte. Voir [Économie du contexte](context.md).
2. **En cas de doute, commencez par `clarify_step`.** Sur du long-horizon, « avoir mal compris
   l'objectif » est l'erreur la plus chère, et c'est précisément le type d'erreur que les couches
   d'économie de contexte ne peuvent pas nettoyer. Voir [Clarification préalable](clarify.md).
3. **Une tâche déléguée doit se suffire à elle-même.** Un subagent part d'un contexte vierge ; il
   ne sait pas ce que sait le [coordinateur](../reference/glossary.md#协调者). Mettez le contexte
   nécessaire dans le task brief, ou dites-lui quel artefact lire.
4. **Les sorties longues passent par le disque, pas par la réponse.** C'est déjà écrit dans
   `WORKER_RULES` ; que vos `instructions` n'aillent pas l'annuler (« recolle-moi le log complet »).
5. **Le `gate` doit d'abord filtrer sur des conditions dures.** Le fichier existe-t-il, le code de
   sortie vaut-il 0 — ce qu'une ligne de Python peut trancher ne se délègue pas à un modèle. Si vous
   voulez qu'un modèle tranche, utilisez `with_goal` tel quel — il remplace le gate par une
   implémentation qui lance un [juge](../reference/glossary.md#判定者) indépendant ; n'en
   bricolez pas un vous-même dans le gate.
6. **Modifications parallèles du même dépôt : `worker(isolate=True)`.** La finalisation (merge,
   nettoyage des worktrees, ouverture de PR) reste pour l'instant à la charge de votre workflow ; le
   harness garantit seulement que les modifications atterrissent chacune dans son propre worktree.

### Le workbench doit être accroché au Workflow {#工作台要挂在-workflow-上}

Dès que le workflow doit écrire des fichiers dans le [workbench](../reference/glossary.md#工作台) —
cas typique : `clarify_step(brief_path=...)` — vous devez créer vous-même un `Workbench` et
l'accrocher **à la fois** à `Workflow.workbench` et au `Runtime` :

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

Accrocher `channel` au workflow a deux raisons : `run()` branche son `on_event` sur la même sortie
d'événements (uniquement si `channel.on_event` vaut encore `None`), et le programme pilote se sert de
ce champ pour savoir à qui répondre.

!!! warning "Reconstruire le chemin du workbench à la main échoue silencieusement"
    L'emplacement par défaut de `Runtime(workbench=True)` est `<run_dir>/workbench`, tandis que celui
    de `Workbench(ws)` est `<ws>/.flower` — **ce ne sont pas le même répertoire**. Quand le workflow
    est appelé par la CLI, il ne voit pas `run_dir` ; reconstruire le chemin soi-même mène ailleurs,
    et alors le brief est écrit dans le répertoire A pendant que l'index injecté scrute le répertoire
    B, **sans la moindre erreur**. Créez un seul objet partagé des deux côtés et le problème
    disparaît ; quand `Workflow.workbench` existe, le `-W` de la ligne de commande est ignoré, c'est
    lui qui fait foi.

### `continuous=True` : relancer une seconde fois sur le même chemin {#continuoustrue同一个路径再跑一次}

Les trois modes ci-dessus concernent l'enchaînement des étapes **à l'intérieur d'une exécution**.
L'inter-processus est un autre axe :

```python
Workflow([...], continuous=True)     # valeur par défaut
```

Relancé dans le même workspace, chaque étape reprend la parole dans la session de la fois précédente
— grâce à la table « nom d'étape → session_id » de `<run_dir>/lineage.json`. Au chargement, chaque
entrée passe par `runtime.has_session()` pour vérifier que la session est toujours en base, et n'est
utilisée que si elle est vivante : le fichier de lignée peut survivre à `sessions.db`, et faire un
resume sur une session inexistante n'explose qu'une fois le sous-processus démarré.

Trois conséquences :

- **`resume_from=None` ne veut pas dire « session neuve ».** C'est vrai à la première exécution, plus
  à la seconde. Pour avoir une session neuve à chaque fois, écrivez explicitement
  `Workflow(..., continuous=False)`.
- **En [continuité](../reference/glossary.md#接续), le contexte ne cesse de croître.** Si vous voulez
  dire autre chose à la reprise, utilisez `Step.resume_prompt` — ce qui est déjà dans le contexte de
  l'interlocuteur n'a pas à être renvoyé.
- Les étapes qui déclarent explicitement `resume_from` ne sont pas affectées ; il est prioritaire.

!!! warning "Le nom d'étape est la clé inter-processus"
    Renommer une étape revient à couper sa lignée : la prochaine exécution ne reprend plus, et
    **aucune erreur n'est signalée**. Les noms de retry suffixés `#retry1` / `#round2` **n'entrent pas
    dans la lignée** (c'est toujours le nom d'origine qui est enregistré) ; c'est aussi l'une des
    façons dont « le juge est toujours une nouvelle session » est implémenté.

Conception complète et `--new` : voir [Continuité](continuity.md).

## Quand ne pas l'utiliser {#什么时候不该用它}

- **Un seul agent à lancer, sans verdict** — n'enveloppez pas dans un `Workflow`. Faites directement
  `await rt.run(spec, "…")`, ou en ligne de commande `flower once "读一眼这个仓库"`.
- **La forme est exactement « clarifier le besoin → fixer l'objectif → travailler »** — utilisez
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) tel
  quel, pas la peine de l'écrire :

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Il fait **trois étapes** : `确认需求` → `设定目标` → `干活` (avec boucle de verdict, l'étape de
    verdict s'appelant `干活·判定#N`). Avec `goal=False`, il n'y a ni deuxième étape ni boucle de
    verdict ; avec `clarify_only=True`, seule la première étape reste. Il embarque son propre
    `HumanChannel` et son `Workbench` et les accroche au workflow, donc `Runtime(workbench=wf.workbench)`
    se réutilise directement — n'en fabriquez pas un autre.

    Sans écrire de code non plus : dans le répertoire du projet, `flower "帮我做一个 X"` lance
    exactement cela. **Ce n'est pas « la conception de workflow recommandée »**, seulement de quoi
    démarrer sans configuration.

- **Un découpage plus fin qu'« un objectif recevable »** — perte nette. Chaque étape ouvre une
  nouvelle session, et une nouvelle session a un plancher de démarrage (mesuré à environ 34k de
  contexte pour le coordinateur), impossible à amortir.
- **Vouloir revenir après coup à un message précis** — cette voie n'existe pas dans `Workflow`, il ne
  transmet jamais `resume_at`. Appelez directement
  `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`.

Le choix des rôles (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) et la sémantique champ
par champ de `Step` et `Workflow` sont dans [l'API Python](../reference/api.md) ; les termes sont dans
le [glossaire](../reference/glossary.md).
