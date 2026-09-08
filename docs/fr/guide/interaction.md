# Changer de couche d'interaction

Le cœur de flower ignore l'existence de toute UI. Chaque chose qui se produit dans une exécution — le modèle parle, appelle un outil, le contexte est presque plein, il faut poser une question à un humain — est aplatie vers une seule et même structure de données : [`Event`](../reference/glossary.md#事件).
**La [couche d'interaction](../reference/glossary.md#交互层) ne connaît que `Event` et n'importe aucun type du SDK.**
C'est la frontière qui permet de changer d'UI sans toucher au cœur : terminal, Web, service HTTP, entièrement automatique et sans surveillance — ce qui change, c'est le consommateur d'`Event`, rien d'autre, pas une ligne.

## Quel problème cela résout {#解决什么问题}

Le flux de messages du SDK expose des **types internes** : `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage`… Les consommer directement dans l'UI a deux conséquences : dès que le SDK monte de version, le front doit suivre ; et comme chaque forme de message est différente, chaque UI doit réécrire la logique « est-ce du corps de texte ou un appel d'outil ».

`normalize(message)` transforme un message du SDK en 0 à N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
Le coût est une conversion ; ce qu'on obtient, c'est l'absence de dépendance de type entre la couche d'interaction et le SDK.

Cette frontière règle au passage quatre choses moins évidentes, toutes les quatre dans `normalize()` :

1. **Les prises de parole des [subagents](../reference/glossary.md#subagent) sont marquées** (`payload["subagent"]`).
   Sans cela, le [brief de tâche](../reference/glossary.md#任务书) envoyé et les paroles intermédiaires du subagent se mélangeraient au corps de texte du [thread principal](../reference/glossary.md#主线程), et pollueraient ensuite, le long du [workflow](../reference/glossary.md#流程), le prompt de l'étape suivante.
2. **Les messages d'erreur synthétiques produits lors d'une coupure réseau sont aiguillés vers `kind="error"`**. Lors d'une coupure, le SDK écrit `API Error: …` dans le transcript comme s'il s'agissait d'un message assistant ; ça ressemble à une parole du modèle (`model` vaut `"<synthetic>"`).
   Si on ne l'intercepte pas ici, ça finit dans `StepResult.text`, puis est transmis à l'[étape](../reference/glossary.md#步骤) suivante.
3. **Les frontières de compact sont signalées explicitement** (`kind="reset"`). Après la frontière, le modèle ne « se souvient » que du résumé, et le cache de prompt est rompu à cet endroit — une exécution à [long horizon](../reference/glossary.md#长程) doit pouvoir le voir.
4. **Le niveau de contexte sort avec chaque message** (`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`). C'est la seule source du critère de [handoff](../reference/glossary.md#换代).

## Comment s'en servir (code minimal) {#怎么用最小代码}

Une couche d'interaction doit brancher trois choses : **la sortie d'événements** (où rendre), **le canal de questions** (qui répond), **l'interruption** (comment crier stop).
Le bloc ci-dessous branche tout, il tourne tel quel :

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Rend l'Event dans votre propre UI — c'est la seule chose à remplacer."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" qui n'est pas du mail : traité plus bas par answerer (mode pull)


async def answerer(ch: HumanChannel) -> None:
    """Récupération des questions en mode pull. Pour du Web / HTTP, c'est l'autre endroit à changer."""
    while True:
        ask = await ch.next_ask()           # sans timeout, on attend indéfiniment
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime utilise le workbench déjà créé par le workflow — n'en fabriquez pas un autre
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # ferme la connexion SQLite
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

Deux finitions faciles à oublier : `rt.close()` doit impérativement être dans `finally` ; si `ctx["_failed_at"]` a une valeur, c'est que l'exécution s'est arrêtée en route (`on_fail="stop"`) — ne la prenez pas pour un succès.

!!! note "Il n'y a qu'un seul workbench, n'en fabriquez pas un autre"
    Le [workbench](../reference/glossary.md#工作台) créé par `Runtime(workbench=True)` se trouve dans
    `<run_dir>/workbench`, alors que `Workbench(ws)` est par défaut dans `<ws>/.flower` —
    ce ne sont pas le même répertoire. Un programme pilote qui fabrique lui-même le chemin pour aller chercher `需求.md` obtient
    « le brief est écrit dans le répertoire A, l'index injecté scanne le répertoire B » — sans la moindre erreur.
    Soit vous passez à `Runtime` celui que le workflow a créé (l'écriture ci-dessus),
    soit vous utilisez la sonde en lecture seule `wake_state()` pour lui demander où il est.

### Trois sorties d'événements {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. un seul agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. tout le workflow, transmis à chaque étape
wf = Workflow(steps=[...], channel=ch)                  # 3. canal de questions, branché sur la même sortie
```

Le branchement du troisième cas se fait dans `Workflow.run` : **il n'est automatique que si `on_event` est non `None` et que `channel.on_event` est encore `None`**. Si vous l'avez branché vous-même, il n'est pas écrasé :

```python
ch = HumanChannel(on_event=my_own_sink)     # branché à la main, Workflow n'y touche pas
```

`on_step(step, result)` est un autre callback, appelé une fois à la fin de chaque étape (**y compris en cas d'échec**), et il reçoit le `StepResult` complet. Barre de progression, écriture sur disque, alertes : accrochez-les ici, n'essayez pas de les reconstituer depuis le flux d'`Event` — le corps de texte est découpé en plusieurs morceaux par les handoffs et les retries.

### Terminal : celui par défaut {#终端默认的那个}

Il y en a un même sans écrire de code. `flower "帮我做一个 X"` passe par
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
qui est une **implémentation de référence de la couche d'interaction, pas une partie du framework** ; elle peut être remplacée intégralement. Les options sont dans la [référence CLI](../reference/cli.md).
Disons la taille telle qu'elle est. `cli.py` en entier fait 1264 lignes, 57KB — mais **ce n'est pas l'ensemble qu'il faut remplacer**.
Le vrai point de remplacement, c'est la `class Render` à l'intérieur (`cli.py:489-687`, 197 lignes), dont la docstring dit justement :
« Event → terminal. Changer d'UI, c'est changer cette seule classe. » Les mille et quelques lignes restantes sont l'interruption, l'oracle, les accusés de réception de la boîte de réception, le sauvetage sur signal — de l'outillage **spécifique au terminal**, qu'il n'y a de toute façon pas lieu de recopier pour du Web ou du HTTP.

Donc l'affirmation « environ 200 lignes remplaçables en bloc » tient — à condition qu'elle désigne `Render`, pas `cli.py`.

Si vous écrivez votre propre UI terminal, le point clé est le thread qui lit l'entrée standard :

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lit l'entrée standard en continu : s'il y a une question en attente c'est une réponse, sinon ça va dans la boîte de réception. Renvoie le drapeau d'arrêt."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # polling, seul moyen de réagir au drapeau d'arrêt
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # sûr entre threads
            else:
                ch.send(raw)                    # va dans la boîte de réception, n'interrompt pas le travail en vol

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Les trois points ont été appris à la dure :

- **Utiliser un thread daemon, pas `asyncio.to_thread(input, ...)`.** `input()` bloqué ne peut pas être annulé, et `asyncio.run` doit joindre les threads de l'exécuteur par défaut avant de sortir — résultat : le travail est fini, mais il faut encore appuyer une fois sur Entrée pour quitter.
- **Faire du polling avec `select`, pas un `input()` direct dans la boucle.** Même problème d'annulation : un thread bloqué sur `input()` ne sera jamais réveillé par `stop.set()`.
- **Lire en continu, pas seulement quand il y a une question.** Si on ne lit que quand il y a une question, tout ce qui a été tapé pendant les heures de travail reste dans le tampon du terminal et sera avalé comme réponse à la question suivante — l'humain n'a même pas encore vu la question qu'elle est déjà « répondue ».

### Web : file d'attente + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # synchrone, dans le thread de la boucle d'événements, ne doit pas bloquer
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # une erreur du front ne doit pas emporter trois heures de travail
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # thread de traitement des requêtes — un autre thread, c'est la norme
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` est l'objet SDK d'origine (un `Ask` dans les événements `ask`) : **non sérialisable en JSON, et à ne pas transmettre au front** — utiliser `raw`, c'est réattacher le front aux types du SDK, et toute cette couche n'aura servi à rien. Les quatre champs `kind` / `text` / `tool` / `payload` suffisent.

### HTTP : numéro de séquence + polling {#http序号--轮询}

Sans connexion longue, numérotez les événements pour que le client les tire :

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # on ne garde que les plus récents, la mémoire ne croît pas avec la durée de l'exécution


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # ce qui est en attente de réponse en ce moment
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = cette question n'est plus en attente
```

Deux limites à reconnaître : quand `maxlen` est plein, les plus anciens sont perdus, et un client qui revient avec un `after` très vieux n'obtiendra pas tout — l'intervalle de polling doit être cohérent avec cette longueur ; et **il faut absolument donner une valeur finie à `timeout_s`** — quand personne ne fait de polling, une question ne se termine pas d'elle-même, et `timeout_s=None` laisse toute l'exécution suspendue pour toujours. La valeur par défaut de `1800.0` secondes est appropriée.

### Entièrement automatique, sans surveillance : personne {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # tous les événements sont jetés
```

L'équivalent en ligne de commande est `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (idem pour les négatifs) est le mode entièrement automatique : la question **n'entre pas dans la file d'attente et n'émet pas d'événement `asked`**, elle est immédiatement soldée en `state="timeout"`, et l'outil renvoie ce texte fixe —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— et l'exécution continue sans encombre. Les questions-réponses restent ajoutées à `HumanChannel(log_path=...)` (`starter_flow` branche par défaut `<工作台>/notes/问答记录.md`), ce qui permet de voir après coup ce qui a été demandé et quelles hypothèses ont été prises.

Si vous ne voulez pas qu'il ouvre la bouche, utilisez `max_asks=0` : la question est directement refusée (`state="over_budget"`), sans bloquer non plus.
Attention, ce n'est **pas** « retirer l'outil » — `allowed_tools` n'est pas exclusif : dès qu'un `channel` est branché sur le [coordinateur](../reference/glossary.md#协调者), les deux outils `mcp__human__ask` et `mcp__human__inbox` sont donnés ensemble, et restent appelables qu'ils soient listés ou non. Seuls le quota et le timeout peuvent empêcher une question.

!!! warning "Sans surveillance, ne laissez jamais une question attendre indéfiniment"
    `timeout_s=None` veut dire « attendre pour toujours ». Quand personne ne regarde, une seule question suffit à figer sur place une exécution de dix heures,
    sans erreur, sans timeout, et sans que les logs montrent la moindre différence. Sans surveillance, il n'y a que deux valeurs correctes : `0` (échec immédiat)
    ou un nombre fini de secondes.

## Ce qu'il fait réellement {#它实际做了什么}

### La forme d'`Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valeurs, voir le tableau ci-dessous
    text: str = ""
    tool: str = ""                      # renseigné uniquement pour tool_call
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objet SDK d'origine / Ask, y toucher c'est se réattacher au SDK
```

`str(ev)` : pour `tool_call` c'est `[nom d'outil] résumé`, sinon c'est `text` ; si `text` est vide, c'est `<kind>`.

### Les 15 `EventKind` {#15-个-eventkind}

| `kind` | Émis par | Quand il apparaît | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Corps de texte du modèle | Le texte | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloc de réflexion | Le contenu de la réflexion | idem |
| `prompt` | `normalize()` | **Entrée** : votre prompt, le brief de tâche envoyé à un subagent | Le texte d'entrée | idem |
| `tool_call` | `normalize()` | Le modèle lance un appel d'outil | Résumé (`file_path` / `command` / `pattern`, tronqué à 200 caractères) | `id`, `input` + idem ; `tool` est le nom de l'outil |
| `tool_result` | `normalize()` | Retour d'un outil | Les 500 premiers caractères (vide si le contenu n'est pas une chaîne) | `tool_use_id`, `is_error` + idem |
| `result` | `normalize()` | Fin d'une requête SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Message synthétique lors d'une coupure réseau | Le texte d'erreur | `synthetic: True` |
| `reset` | `normalize()` | Frontière de compact ou réinitialisation de session | `压缩(trigger) 167000 → 42000 tokens` ; pour une réinitialisation de session, `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vide lors d'une réinitialisation de session) |
| `system` | `normalize()` | Les autres messages système du SDK | subtype | `data` transmis tel quel |
| `task` | `normalize()` | Message de progression d'une tâche | **vide** | `kind` = nom de la classe du message SDK |
| `unknown` | `normalize()` | Type de message non reconnu | Nom de la classe | — |

!!! note "Le corps de `task` est vide, ne l'affichez pas tel quel"
    `TaskProgressMessage` et consorts sont des types de messages internes au SDK. Auparavant, `normalize()` émettait le nom de la classe comme corps de texte ;
    à l'écran, c'est du bruit pur, et mélangé au corps de texte de l'agent ça donne l'impression d'une erreur (constaté en pratique). Aujourd'hui, c'est un événement
    **sans corps de texte**, le nom de la classe étant placé dans `payload["kind"]` — c'est à la couche d'interaction de décider de l'afficher ou non
    (`events.py`).
| `ask` | `HumanChannel` | Il faut une réponse humaine, une question a trouvé son issue, ou un humain a parlé de lui-même | La question / la parole de l'humain | Deux identités, voir plus bas |
| `retry` | `Runtime` | Retry en cours / en attente du réseau | Une phrase d'explication | `step`, `attempt` |
| `step` | `Workflow.run` | Frontière d'étape | Nom de l'étape | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff : approche / écriture en cours / terminé | Une phrase avec le niveau de contexte | `phase`, `step`, `context`, `window` + voir plus bas |

**Quatre kinds ne sont pas produits par `normalize()`** : `ask` vient de `HumanChannel`, `retry` et `handoff` viennent de `Runtime`, `step` vient de `Workflow.run`. Les mettre dans le même `EventKind` est délibéré —
**l'UI ne connaît qu'un seul jeu d'`Event`, sans avoir à ouvrir une voie séparée pour « il faut une réponse humaine » ou « frontière d'étape ».**

En écrivant une UI, laissez une branche `else`. `EventKind` gagnera de nouveaux membres, et une vieille UI ne devrait pas planter pour autant.

### Les trois phases de `handoff` {#handoff-的三个-phase}

| `phase` | Quand c'est émis | Extras dans `payload` |
|---|---|---|
| `near` | Le niveau a dépassé `warn_at`. **Émis une seule fois par génération**, pas de spam | `at` (le seuil de handoff) |
| `writing` | Début de l'écriture du [document de handoff](../reference/glossary.md#交接书). L'écriture prend une dizaine de secondes ; sans cet événement l'interface a l'air figée | — |
| `done` | Handoff écrit, bascule vers une nouvelle session | `degraded` (version dégradée ou non), `path` (où c'est écrit, chaîne vide sans workbench), `sections` |

Pour le mécanisme lui-même, voir [handoff](handoff.md).

### Les deux identités d'`ask` {#ask-的两种身份}

`Event("ask")` porte à la fois « une question » et « une parole spontanée de l'humain ». **L'UI doit d'abord regarder `payload["kind"]`** :

| Identité | Comment la reconnaître | `payload` |
|---|---|---|
| Une question | Pas de clé `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at` ; `raw` est l'objet `Ask` |
| Une parole spontanée de l'humain | `payload["kind"] == "mail"` | `kind`, `state` (`queued` déposé / `delivered` récupéré), `id`, `amended` (dans quel fichier c'est ajouté, chaîne vide si non configuré). **Pas d'`options` ni de `remaining`** |

Une question émet **au moins deux** événements : un au moment de la question (`state="asked"`), un autre à l'issue
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). L'UI n'a qu'à mettre à jour la même entrée d'après `payload["id"]`.

### Demander à l'humain : `Ask` et `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # voir les cinq issues ci-dessus
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # secondes d'attente, une décimale
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` est un serveur MCP in-process plus un jeu de méthodes destinées à l'UI. Côté modèle, seuls deux outils sont visibles :
`mcp__human__ask` (poser une question, ça suspend et attend) et `mcp__human__inbox` (consulter la boîte de réception, **sans blocage** ; si elle est vide, ça renvoie immédiatement une phrase d'explication). Construction complète :

```python
HumanChannel(
    *,                                  # tout en keyword-only
    on_event=None,                      # sortie en mode push. Workflow ne la branche automatiquement que si elle vaut None
    max_asks=None,                      # None = illimité ; 0 = interdit de demander. Au-delà du quota, refus direct, sans blocage
    timeout_s=1800.0,                   # None = attendre pour toujours ; <= 0 = échec immédiat
    log_path=None,                      # les questions-réponses sont ajoutées à ce fichier, sans occuper le contexte
    amend_path=None,                    # ce que l'humain dit en cours d'exécution est ajouté à ce fichier, en général le brief
    over_budget_text=OVER_BUDGET,       # trois réponses fixes, remplaçables par les vôtres
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` est le paramètre le plus facile à oublier, et c'est lui qui détermine si « les exigences modifiées en cours de route par l'humain » survivent aux frontières d'étape.
Chaque étape est une nouvelle [session](../reference/glossary.md#会话) avec un instantané figé en lecture seule : ce qui est dit en cours d'exécution n'entre que dans le contexte de l'agent du moment ; l'étape suivante (par exemple le [verdict](../reference/glossary.md#判定)) est une session toute neuve qui lit `需求.md` et `目标.md`, **et ne voit pas ce que vous avez dit** — elle juge donc encore selon les anciennes limites et déclare hors périmètre ce qui vient d'être corrigé.
`amend_path` **ajoute** chaque message au [brief](../reference/glossary.md#需求确认书) — en ajout et non en écrasement : l'exigence initiale est de l'histoire, et voir ce qui a changé vaut mieux que ne pas le voir. `starter_flow` branche par défaut
`<工作台>/notes/需求.md`.

Constaté en pratique ($0.6767), ce mécanisme marche encore mieux que prévu : l'humain dit « au passage, rapporte le nombre total d'octets » ; le coordinateur consulte la boîte de réception et rapporte —
« hand l'a déjà lu dans le complément en cours d'exécution de `.flower/notes/需求.md` et l'a calculé, pas besoin de redéléguer ».
**Le subagent l'a lu dans le fichier, sans que personne le lui répète.**

Membres publics :

| Membre | Signature | Sémantique |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | À passer directement à `AgentSpec.mcp_servers`. Le nom de la clé doit correspondre au nom du serveur, d'où le fait qu'il soit fourni ici |
| `ask` | `async (question, options=None) -> Ask` | Suspend et attend l'humain. **Ne lève jamais d'exception hormis `CancelledError`** — l'absence de réponse est aussi une réponse, distinguée par `ask.state` |
| `pending` | `() -> list[Ask]` | Les questions actuellement en attente de réponse |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Pour les UI en mode pull. Renvoie `None` en cas de timeout, lève si annulé |
| `answer` | `(ask_id, text) -> bool` | Répondre. `False` = cette question n'est plus en attente (timeout / déjà répondue) |
| `decline` | `(ask_id, reason="") -> bool` | Passer, en laissant le modèle juger lui-même et écrire son hypothèse dans « Inconnues et hypothèses » |
| `send` | `(text) -> Mail \| None` | L'humain dit spontanément une phrase, qui va dans la boîte de réception. N'interrompt pas l'agent ; appelle automatiquement `amend()` en interne |
| `amend` | `(text, *, label="运行中补充") -> bool` | Ajoute à `amend_path`. Renvoie si l'écriture a vraiment eu lieu (chemin non configuré / texte vide / `OSError` donnent tous `False`) |
| `pending_mail` | `() -> list[Mail]` | Les paroles pas encore récupérées |
| `remaining` | `-> int` | Nombre de questions encore possibles. Avec `max_asks=None`, renvoie **`-1`**, pas 0 |
| `transcript` | `() -> str` | Le markdown de l'historique des questions-réponses |
| `asks` / `mail` / `ui_errors` | `list` | Toutes les questions / toutes les paroles de l'humain / les exceptions levées par les callbacks de l'UI |

`answer`, `decline` et `send` **peuvent être appelés depuis n'importe quel thread**. Le thread de traitement des requêtes d'un backend Web, le thread d'entrée d'une TUI sont dans d'autres threads — c'est la norme, pas un cas limite. En interne, ça passe par `loop.call_soon_threadsafe`, car
`asyncio.Future.set_result` n'est pas thread-safe.

Push et pull sont deux modes de récupération : **choisissez-en un** :

| | Comment récupérer | Convient à |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, réception d'un `kind == "ask"` avec `payload["state"] == "asked"` | UI événementielles (push Web, redessin de TUI) |
| **Pull** | `await channel.next_ask()` | Une tâche d'entrée indépendante |

Trois sémantiques « 0 / None » toutes différentes ; les confondre, c'est un blocage définitif sans surveillance ou pas la moindre question posée :

| Écriture | Signification |
|---|---|
| `max_asks=None` | Nombre illimité (défaut) |
| `max_asks=0` | Questions interdites, refus direct |
| `timeout_s=None` | Attendre pour toujours |
| `timeout_s<=0` | Ne pas attendre, la question échoue immédiatement |
| `remaining` renvoie `-1` | La valeur quand `max_asks=None`, pas 0 |

### Interruption : n'importe quel thread peut crier stop {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")` ; une chaîne vide interrompt sans rien dire. Trois propriétés :

- **Reprise de la même session** (`resume`), pas un redémarrage à zéro — le travail déjà fait et le contexte sont conservés. On réutilise la voie existante du retry après coupure réseau, en remplaçant simplement la « cause de l'échec » par « l'humain a interrompu » et le `resume_prompt` par la parole de l'humain.
- **Ne consomme pas `max_attempts`**. C'est un quota pour les pannes, pas pour les humains.
- **Coopératif** : on coupe à une frontière de message, sans annuler brutalement la tâche. Le coût, c'est un délai jusqu'au message suivant (si un subagent est en cours, il faut attendre son retour) ; ce qu'on gagne, c'est de ne pas déchirer l'état en plein milieu.

Le coût, dit tel quel : une interruption fait **perdre le travail à moitié fait d'un subagent en vol** (constaté lors de la coupure réseau HT001, voir
[issue #2](https://github.com/ChenyuHeee/flower/issues/2)). L'implémentation de référence du terminal l'écrit explicitement dans son invite, pour qu'on le sache avant d'appuyer ; votre propre UI devrait faire pareil.

Si vous ne voulez pas interrompre mais simplement ajouter une exigence, utilisez la boîte de réception (`ch.send(...)`) — elle n'interrompt rien, et le délai est le prochain point de contrôle de l'agent.

### Oracle : poser une question sans déranger l'exécution {#旁路顾问问一句而不打扰运行}

Pour savoir « où on en est », inutile d'interrompre, et il ne faut pas demander au coordinateur : cet échange **occuperait définitivement le contexte du thread principal**
(qui contient des décisions, pas un historique de questions-réponses), et il devrait interrompre ce qu'il est en train de faire. Sur une exécution de dix heures, trois questions posées en passant suffisent à payer ces deux coûts.

L'[oracle](../reference/glossary.md#旁路顾问) est une voie latérale en lecture seule. Ses seuls outils sont `Read` / `Glob` /
`Grep`, il a le workbench ouvert, et il vient avec des garde-fous par défaut : `max_turns=12`, `max_budget_usd=0.5`. Dans le terminal, une ligne commençant par `?` le déclenche ; il répond à partir de deux choses : la fenêtre d'événements récents (60 entrées, fixe) et le brief, les objectifs, les notes et les livrables du workbench.
Il utilise son propre `Runtime` (`<run_dir>/aside`), de sorte que le coût et le [lignage](../reference/glossary.md#血缘) de session
**ne se mélangent pas au manifeste principal** — ce manifeste consigne « quelles étapes cette exécution a effectuées », et une question posée en passant n'est pas une étape.

Constaté en pratique : deux questions pour $0.5190 au total, sans un octet de plus dans le manifeste de l'exécution principale.

### Deux règles dures {#两条硬规矩}

!!! warning "on_event ne doit ni bloquer, ni laisser échapper d'exception"
    **Un. `on_event` est une fonction synchrone, appelée dans le thread de la boucle d'événements.** Donc
    `asyncio.Queue.put_nowait()` est sûr, `await` ne l'est pas (ce n'est pas une coroutine), et **la bloquer, c'est bloquer toute l'exécution**.
    Si vous avez du travail lent à faire, déposez-le dans une file et laissez une autre tâche s'en charger.

    **Deux. Lever une exception dans `on_event` abîme l'exécution elle-même.** Les événements de type corps de texte sont émis à l'intérieur du bloc `try` de `Runtime._attempt` : l'exception est enregistrée comme `result.error` — l'étape est déclarée en échec ; les événements `retry` sont émis en dehors de ce bloc, et l'exception remonte directement hors de `Runtime.run`. Le front ne doit pas emporter trois heures de travail : **enveloppez vous-même dans un try**.

    Exception : les événements `ask` émis par `HumanChannel` lui-même sont déjà enveloppés, les exceptions étant collectées dans `channel.ui_errors`,
    sans interrompre l'exécution.

## Quand ne pas s'en servir {#什么时候不该用它}

### Ce qu'il ne faut pas faire dans la couche d'interaction {#交互层里不该做的事}

| À ne pas faire | Pourquoi | Que faire à la place |
|---|---|---|
| `from claude_agent_sdk import ...` | Dès que la couche d'interaction dépend des types du SDK, le front doit suivre à chaque montée de version, et cette couche n'aura servi à rien | N'utiliser que `kind` / `text` / `tool` / `payload` d'`Event` |
| Lire `ev.raw` | Idem, et en plus ce n'est pas sérialisable en JSON | S'il manque un détail, ajoutez-le au `payload` dans `normalize()`, ne contournez pas la frontière |
| `await`, requêtes réseau ou écritures disque lentes dans `on_event` | C'est synchrone, appelé sur le thread de la boucle d'événements ; le bloquer, c'est bloquer toute l'exécution | `put_nowait()` dans une file, une autre tâche consomme |
| Laisser `on_event` propager une exception | Une exception sur un événement de corps de texte devient `result.error`, et l'étape est déclarée en échec | Envelopper tout le corps du callback dans un `try` |
| Utiliser `disallowed_tools` pour couper les questions | C'est **au niveau de la session**, ce qui désactive aussi l'outil homonyme des subagents (message d'erreur constaté : `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` ou `timeout_s=0` |
| Retirer `mcp__human__ask` d'`allowed_tools` en croyant interdire les questions | `allowed_tools` n'est pas exclusif : c'est une liste d'exemption d'approbation, pas une liste blanche ; brancher un `channel` donne les deux outils ensemble | Idem |
| Fabriquer soi-même le chemin pour trouver `需求.md` / `目标.md` | Il y a deux emplacements possibles pour le workbench ; se tromper ne produit aucune erreur, juste un échec silencieux | `wake_state()` ou `wf.workbench` |
| Reconstituer progression et résultat depuis le flux d'`Event` | Le corps de texte est découpé en plusieurs morceaux par les handoffs et les retries | `on_step(step, result)` pour obtenir le `StepResult` complet |
| `timeout_s=None` sans surveillance | Personne ne répond, l'exécution reste suspendue pour toujours, sans erreur ni timeout | `0`, ou un nombre fini de secondes |

### Quand il n'y a tout simplement rien à remplacer {#什么时候根本不用换}

- **Vous voulez seulement changer les couleurs, afficher une ligne de plus ou de moins** — il suffit de modifier la fonction de rendu. Dans l'implémentation de référence du terminal, l'interruption, l'oracle, les accusés de réception de la boîte de réception, le sauvetage sur SIGHUP / SIGTERM, l'attente de la fin de la voie latérale avant de quitter : tout réécrire coûte cher.
- **Vous voulez seulement exécuter une étape, sans interaction** — utilisez `flower once`. Il ne passe pas par le pilote interactif : il n'a de toute façon ni interruption Ctrl+C, ni thread de réponse sur l'entrée standard, ni oracle, ni sauvetage sur signal.
- **Ce que vous voulez changer, c'est en fait le workflow, pas l'UI** — voir [Concevoir un workflow](workflow.md). La couche d'interaction décide seulement qui regarde et qui répond ; c'est `Workflow` qui décide du nombre d'étapes, de la manière de juger et du moment de sortir par anticipation.
- **Ce que vous voulez changer, c'est le stockage de session, le modèle ou le budget** — aucun de ces trois éléments n'est sur cette frontière, voir la [référence de l'API Python](../reference/api.md).
