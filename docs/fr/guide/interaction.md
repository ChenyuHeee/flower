# Changer de couche d'interaction

Le cœur de flower ignore l'existence de l'UI. Tout ce qui se passe dans un run — le modèle parle,
il appelle un outil, le contexte est presque plein, il faut poser une question à un humain — est
aplati vers une seule et même structure de données : [`Event`](../reference/glossary.md#事件).
**La [couche d'interaction](../reference/glossary.md#交互层) ne connaît que `Event` et n'importe
aucun type du SDK.** C'est la frontière qui permet de changer d'UI sans toucher au cœur : terminal,
Web, service HTTP, autonome sans surveillance — ce qui change, c'est le consommateur d'`Event`,
pas une ligne d'autre chose.

## Quel problème ça résout {#解决什么问题}

Le flux de messages du SDK est fait de **types internes** : `AssistantMessage`, `ToolUseBlock`,
`ToolResultBlock`, `ResultMessage`, `SystemMessage`… Les consommer directement depuis l'UI a deux
conséquences : dès que le SDK monte de version, le front doit suivre ; et comme chaque message a
une forme différente, chaque UI doit réécrire la logique « est-ce du texte ou un appel d'outil ».

`normalize(message)` convertit un message SDK en 0 à N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
Le coût est une conversion ; le gain est l'absence de dépendance de types entre la couche
d'interaction et le SDK.

Cette frontière règle au passage quatre choses moins évidentes, toutes les quatre dans
`normalize()` :

1. **Les prises de parole des [subagents](../reference/glossary.md#subagent) sont marquées**
   (`payload["subagent"]`). Sinon le [task brief](../reference/glossary.md#任务书) qui distribue le
   travail et les propos intermédiaires du subagent se mélangent au texte du
   [thread principal](../reference/glossary.md#主线程), puis polluent, le long du
   [workflow](../reference/glossary.md#流程), le prompt de l'étape suivante.
2. **Les messages d'erreur synthétiques lors d'une coupure sont dérivés vers `kind="error"`.**
   Lors d'une coupure, le SDK écrit `API Error: …` dans le transcript comme un message assistant ;
   ça ressemble à une parole du modèle (`model` vaut `"<synthetic>"`). Sans interception ici, ça
   entre dans `StepResult.text` et part vers l'[étape](../reference/glossary.md#步骤) suivante.
3. **Les frontières de compact sont signalées explicitement** (`kind="reset"`). Après cette
   frontière, le modèle ne « se souvient » que du résumé, et le cache de prompt est coupé là aussi —
   un run [long-horizon](../reference/glossary.md#长程) doit pouvoir le voir.
4. **Le niveau de contexte accompagne chaque message** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). C'est l'unique source du critère de
   [handoff](../reference/glossary.md#换代).

## Comment s'en servir (code minimal) {#怎么用最小代码}

Une couche d'interaction doit brancher trois choses : **la sortie d'événements** (où afficher),
**le canal de questions** (qui répond) et **l'interruption** (comment dire stop). Le bloc ci-dessous
branche les trois et tourne tel quel :

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
    # les "ask" qui ne sont pas du mail sont traités par answerer ci-dessous (mode pull)


async def answerer(ch: HumanChannel) -> None:
    """Récupération des questions en mode pull. En Web / HTTP, c'est l'autre endroit à changer."""
    while True:
        ask = await ch.next_ask()           # sans timeout, attend indéfiniment
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime réutilise le workbench créé par le workflow — n'en fabriquez pas un autre
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

Deux finitions faciles à oublier : `rt.close()` doit être dans `finally` ; et si `ctx["_failed_at"]`
a une valeur, c'est que le run s'est arrêté en route (`on_fail="stop"`) — ne le prenez pas pour un
succès.

!!! note "Il n'y a qu'un seul workbench, n'en fabriquez pas un autre"
    Le [workbench](../reference/glossary.md#工作台) créé par `Runtime(workbench=True)` se trouve
    dans `<run_dir>/workbench`, alors que `Workbench(ws)` se place par défaut dans `<ws>/.flower` —
    ce ne sont pas le même répertoire. Un programme pilote qui reconstruit lui-même le chemin pour
    trouver `需求.md` se retrouve avec « le brief écrit dans le répertoire A, l'index injecté qui
    scanne le répertoire B » — et sans erreur. Soit vous passez à `Runtime` celui que le workflow a
    créé (l'écriture ci-dessus), soit vous demandez où il est avec la sonde en lecture seule
    `wake_state()`.

### Trois sorties d'événements {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. un seul agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. tout le workflow, transmis à chaque étape
wf = Workflow(steps=[...], channel=ch)                  # 3. canal de questions, branché sur la même sortie
```

Le branchement du troisième cas se fait dans `Workflow.run` : **il n'est automatique que si
`on_event` n'est pas `None` et que `channel.on_event` vaut encore `None`**. Si vous l'avez branché
vous-même, il n'est pas écrasé :

```python
ch = HumanChannel(on_event=my_own_sink)     # branché à la main, Workflow n'y touche pas
```

`on_step(step, result)` est un autre callback, appelé une fois par étape terminée (**échecs
compris**), qui reçoit le `StepResult` complet. Barre de progression, écriture sur disque, alertes :
accrochez-les là, n'allez pas les reconstituer depuis le flux d'`Event` — le texte est découpé en
plusieurs morceaux par les handoffs et les reprises.

### Terminal : celui par défaut {#终端默认的那个}

Il y en a déjà un, sans écrire une ligne. `flower "帮我做一个 X"` passe par
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py), qui est une
**implémentation de référence de la couche d'interaction, pas une partie du framework** : il peut
être remplacé intégralement ; pour les options, voir la [référence CLI](../reference/cli.md).

Soyons précis sur la taille. `cli.py` entier fait 1264 lignes, 57 Ko — mais **ce n'est pas le
fichier entier qu'il faut remplacer**. Le vrai point de remplacement est la `class Render` qu'il
contient (`cli.py:382-578`, 197 lignes), dont la docstring dit exactement : « Event → terminal.
Changer d'UI, c'est changer cette seule classe. » Les mille et quelques lignes restantes sont
l'interruption, l'oracle, les accusés de réception de l'inbox, le sauvetage sur signal — tout un
attirail **propre au terminal**, qu'il n'y a de toute façon pas à reprendre pour du Web ou du HTTP.

Donc l'affirmation « environ 200 lignes remplaçables d'un bloc » tient — à condition qu'elle désigne
`Render`, et non `cli.py`.

Si vous écrivez votre propre UI terminal, le point délicat est le thread qui lit l'entrée standard :

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lit stdin en continu : s'il y a une question en attente, c'est la réponse ; sinon, inbox.

    Retourne le drapeau d'arrêt.
    """
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # polling, pour pouvoir réagir au drapeau d'arrêt
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
                ch.send(raw)                    # va dans l'inbox, n'interrompt pas le travail en cours

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Les trois points viennent de l'expérience :

- **Utilisez un thread daemon, pas `asyncio.to_thread(input, ...)`.** `input()` bloqué ne peut pas
  être annulé, et `asyncio.run` joint les threads de l'exécuteur par défaut avant de sortir — au
  final, le travail est fini mais il faut encore appuyer sur Entrée pour quitter.
- **Faites du polling avec `select`, n'appelez pas `input()` directement dans la boucle.** Même
  problème d'annulation : un thread bloqué sur `input()` ne sera plus jamais réveillé par
  `stop.set()`.
- **Lisez en continu, pas seulement quand il y a une question.** Si vous ne lisez que quand une
  question est posée, tout ce qui a été tapé pendant les heures de travail reste dans le buffer du
  terminal et sera avalé comme réponse à la question suivante — la question est « répondue » avant
  même que l'humain l'ait vue.

### Web : file d'attente + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # synchrone, dans le thread de la boucle d'événements, ne doit pas bloquer
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # une erreur de front-end ne doit pas emporter trois heures de travail
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # thread de traitement des requêtes — un autre thread, c'est la norme
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` est l'objet SDK brut (un `Ask` dans les événements `ask`) : **il n'est pas sérialisable en
JSON, et ne doit pas partir vers le front** — utiliser `raw`, c'est rattacher le front aux types du
SDK, et cette couche n'aura servi à rien. Les quatre champs `kind` / `text` / `tool` / `payload`
suffisent.

### HTTP : numéros de séquence + polling {#http序号--轮询}

Sans connexion longue, numérotez les événements pour que le client vienne les chercher :

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # ne garde que les plus récents, la mémoire ne suit pas la durée du run


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # ce qui attend actuellement une réponse
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = cette question n'attend plus
```

Deux limites à connaître : quand `maxlen` est atteint, les plus anciens sont perdus, donc un client
qui revient avec un `after` trop vieux n'obtiendra pas tout — l'intervalle de polling doit être
cohérent avec cette longueur ; et **il faut donner une valeur finie à `timeout_s`** — quand personne
ne fait de polling, une question ne se termine pas d'elle-même, et `timeout_s=None` suspendra le run
entier pour toujours. La valeur par défaut de `1800.0` secondes convient.

### Autonome sans surveillance : personne {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # tous les événements sont jetés
```

L'équivalent en ligne de commande est `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (idem pour les négatifs) est le mode entièrement automatique : les questions
**n'entrent pas dans la file d'attente et n'émettent pas d'événement `asked`**, elles sont réglées
immédiatement en `state="timeout"`, et l'outil renvoie ce texte fixe —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— et le run continue sans encombre. Les questions et réponses sont tout de même ajoutées dans
`HumanChannel(log_path=...)` (`starter_flow` branche par défaut `<工作台>/notes/问答记录.md`), ce
qui permet de voir après coup ce qui a été demandé et quelles hypothèses ont été prises.

Si vous ne voulez pas qu'il ouvre la bouche du tout, utilisez `max_asks=0` : la question est
directement refusée (`state="over_budget"`), sans blocage non plus. Attention, ce n'est **pas** la
même chose que « retirer l'outil » : `allowed_tools` n'est pas exclusif, et dès qu'un
[coordinateur](../reference/glossary.md#协调者) reçoit un `channel`, les deux outils
`mcp__human__ask` et `mcp__human__inbox` lui sont donnés ensemble — listés ou non, il peut les
appeler. Seuls le quota et le timeout peuvent bloquer une question.

!!! warning "En mode sans surveillance, ne laissez jamais une question attendre indéfiniment"
    `timeout_s=None` signifie « attendre pour toujours ». Quand personne ne regarde, une seule
    question suffit à figer sur place un run de dix heures — sans erreur, sans timeout, et sans
    rien de visible dans les logs. En mode sans surveillance, il n'y a que deux valeurs correctes :
    `0` (échec immédiat) ou un nombre fini de secondes.

## Ce qu'elle fait réellement {#它实际做了什么}

### La forme d'`Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valeurs, voir le tableau ci-dessous
    text: str = ""
    tool: str = ""                      # non vide seulement pour tool_call
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objet SDK brut / Ask ; y toucher, c'est se rattacher au SDK
```

`str(ev)` : pour `tool_call`, c'est `[nom d'outil] résumé` ; sinon c'est `text` ; et si `text` est
vide, c'est `<kind>`.

### Les 15 `EventKind` {#15-个-eventkind}

| `kind` | Émis par | Quand | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Texte du modèle | Le texte | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloc de réflexion | Le contenu de la réflexion | idem |
| `prompt` | `normalize()` | **Entrée** : votre prompt, le task brief confié à un subagent | Le texte d'entrée | idem |
| `tool_call` | `normalize()` | Le modèle déclenche un appel d'outil | Résumé (`file_path` / `command` / `pattern`, tronqué à 200 caractères) | `id`, `input` + idem ; `tool` contient le nom de l'outil |
| `tool_result` | `normalize()` | Retour d'outil | Les 500 premiers caractères (vide si le contenu n'est pas une chaîne) | `tool_use_id`, `is_error` + idem |
| `result` | `normalize()` | Fin d'une requête SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Message synthétique lors d'une coupure | Le texte de l'erreur | `synthetic: True` |
| `reset` | `normalize()` | Frontière de compact ou reset de session | `压缩(trigger) 167000 → 42000 tokens` ; `conversation reset` en cas de reset de session | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vide lors d'un reset de session) |
| `system` | `normalize()` | Les autres messages système du SDK | subtype | `data` transmis tel quel |
| `task` | `normalize()` | Message de progression de tâche | Nom de la classe du message | — |
| `unknown` | `normalize()` | Type de message non reconnu | Nom de la classe | — |
| `ask` | `HumanChannel` | Une question à l'humain, l'issue d'une question, ou un message spontané de l'humain | La question / ce que l'humain a dit | Deux identités, voir plus bas |
| `retry` | `Runtime` | Nouvel essai en cours / attente du réseau | Une phrase d'explication | `step`, `attempt` |
| `step` | `Workflow.run` | Frontière d'étape | Nom de l'étape | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff : approche / écriture en cours / terminé | Une phrase avec le niveau de contexte | `phase`, `step`, `context`, `window` + voir plus bas |

**Quatre `kind` ne sont pas produits par `normalize()`** : `ask` vient de `HumanChannel`, `retry` et
`handoff` viennent de `Runtime`, `step` vient de `Workflow.run`. Les mettre dans le même `EventKind`
est délibéré — **l'UI ne connaît qu'un seul type d'`Event`, sans avoir à ouvrir une autre voie pour
« une question à l'humain » ou « une frontière d'étape ».**

Quand vous écrivez une UI, laissez une branche `else`. `EventKind` gagnera de nouveaux membres, et
une ancienne UI ne doit pas planter pour autant.

### Les trois phases de `handoff` {#handoff-的三个-phase}

| `phase` | Quand | Extras dans `payload` |
|---|---|---|
| `near` | Le niveau a dépassé `warn_at`. **Émis une seule fois par génération**, pas de spam | `at` (le seuil de handoff) |
| `writing` | Début de l'écriture du [document de handoff](../reference/glossary.md#交接书). L'écriture prend une dizaine de secondes ; sans cet événement, l'interface a l'air figée | — |
| `done` | Le handoff est écrit, la nouvelle session est en place | `degraded` (version dégradée ou non), `path` (où il a été écrit ; chaîne vide s'il n'y a pas de workbench), `sections` |

Pour le mécanisme lui-même, voir [handoff](handoff.md).

### Les deux identités d'`ask` {#ask-的两种身份}

`Event("ask")` porte à la fois « une question » et « un message spontané de l'humain » : **l'UI doit
d'abord regarder `payload["kind"]`**.

| Identité | Comment la reconnaître | `payload` |
|---|---|---|
| Une question | Pas de clé `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at` ; `raw` est l'`Ask` |
| Un message spontané de l'humain | `payload["kind"] == "mail"` | `kind`, `state` (`queued` = déposé / `delivered` = récupéré), `id`, `amended` (dans quel fichier il a été ajouté ; chaîne vide si non configuré). **Pas d'`options` ni de `remaining`** |

Une question émet **au moins deux** événements : un à la question (`state="asked"`), un autre à son
issue (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). L'UI n'a qu'à mettre à jour
la même entrée d'après `payload["id"]`.

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

`HumanChannel` est un serveur MCP in-process plus un ensemble de méthodes destinées à l'UI. Côté
modèle, seuls deux outils sont visibles : `mcp__human__ask` (poser une question, avec attente
bloquante) et `mcp__human__inbox` (consulter l'inbox, **sans blocage** : si elle est vide, il rend
immédiatement une phrase d'explication). Constructeur complet :

```python
HumanChannel(
    *,                                  # tout en keyword-only
    on_event=None,                      # sortie push. Workflow ne la branche que si elle vaut None
    max_asks=None,                      # None = illimité ; 0 = interdit. Au-delà : refus, sans blocage
    timeout_s=1800.0,                   # None = attente infinie ; <= 0 = échec immédiat
    log_path=None,                      # les Q/R sont ajoutées à ce fichier, sans occuper le contexte
    amend_path=None,                    # les messages émis en cours de run vont dans ce fichier, en général le brief
    over_budget_text=OVER_BUDGET,       # trois réponses fixes, remplaçables par les vôtres
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` est le paramètre le plus souvent oublié, et c'est lui qui décide si « un besoin modifié
en cours de route survit à la frontière d'étape ». Chaque étape est une nouvelle
[session](../reference/glossary.md#会话) avec une pièce figée en lecture seule : ce qui est dit
pendant le run n'entre que dans le contexte de l'agent du moment ; l'étape suivante (le
[verdict](../reference/glossary.md#判定) par exemple) est une session entièrement neuve, qui lit
`需求.md` et `目标.md` et **ne voit pas ce que vous avez dit** — elle juge donc selon les anciennes
limites et déclare hors périmètre ce qui vient d'être corrigé. `amend_path` **ajoute** chaque message
au [brief](../reference/glossary.md#需求确认书) — ajout et non écrasement : l'ancien besoin devient
de l'historique, et voir ce qui a changé vaut mieux que ne pas le voir. `starter_flow` branche par
défaut `<工作台>/notes/需求.md`.

En conditions réelles ($0.6767), ça marche encore mieux que prévu : l'humain dit « au passage,
rapporte le nombre total d'octets », le coordinateur consulte son inbox et répond — « hand l'a déjà
lu dans les compléments en cours de run de `.flower/notes/需求.md` et l'a calculé, inutile de
redistribuer la tâche ». **Le subagent l'a lu depuis le fichier, sans que personne le lui répète.**

Membres publics :

| Membre | Signature | Sémantique |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | À passer directement à `AgentSpec.mcp_servers`. Le nom de clé doit correspondre au nom du serveur, d'où le fait qu'il le fournisse lui-même |
| `ask` | `async (question, options=None) -> Ask` | Bloque en attendant l'humain. **Ne lève jamais d'exception hors `CancelledError`** — l'absence de réponse est aussi une réponse, à distinguer via `ask.state` |
| `pending` | `() -> list[Ask]` | Les questions actuellement en attente de réponse |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Pour les UI en mode pull. Retourne `None` en cas de timeout, lève si annulé |
| `answer` | `(ask_id, text) -> bool` | Répondre. `False` = cette question n'attend plus (timeout / déjà répondue) |
| `decline` | `(ask_id, reason="") -> bool` | Passer, laisser le modèle décider seul et écrire son hypothèse dans « 未知与假设 » |
| `send` | `(text) -> Mail \| None` | L'humain dit spontanément quelque chose, qui va dans l'inbox. N'interrompt pas l'agent ; appelle `amend()` en interne |
| `amend` | `(text, *, label="运行中补充") -> bool` | Ajoute dans `amend_path`. Retourne si l'écriture a bien eu lieu (chemin non configuré / texte vide / `OSError` donnent `False`) |
| `pending_mail` | `() -> list[Mail]` | Les messages pas encore récupérés |
| `remaining` | `-> int` | Nombre de questions restantes. Avec `max_asks=None`, retourne **`-1`**, pas 0 |
| `transcript` | `() -> str` | Le markdown de l'historique des questions/réponses |
| `asks` / `mail` / `ui_errors` | `list` | Toutes les questions / tous les messages humains / les exceptions levées par les callbacks d'UI |

`answer`, `decline` et `send` **peuvent être appelés depuis n'importe quel thread**. Le thread de
traitement des requêtes d'un back-end Web, le thread d'entrée d'un TUI sont d'autres threads — c'est
la norme, pas un cas limite. En interne, ça passe par `loop.call_soon_threadsafe`, parce que
`asyncio.Future.set_result` n'est pas thread-safe.

Push et pull : **choisissez-en un**.

| | Comment récupérer | Adapté à |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, réagir quand `kind == "ask"` et `payload["state"] == "asked"` | Les UI événementielles (push Web, redessin d'un TUI) |
| **Pull** | `await channel.next_ask()` | Une tâche d'entrée indépendante |

Trois sémantiques de « 0 / None » différentes : les confondre donne un blocage mort en mode sans
surveillance, ou un agent qui ne pose jamais aucune question.

| Écriture | Sens |
|---|---|
| `max_asks=None` | Nombre de questions illimité (par défaut) |
| `max_asks=0` | Questions interdites, refus immédiat |
| `timeout_s=None` | Attente infinie |
| `timeout_s<=0` | Aucune attente, la question échoue immédiatement |
| `remaining` retourne `-1` | La valeur quand `max_asks=None`, pas 0 |

### Interruption : n'importe quel thread peut dire stop {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")` ; une chaîne vide interrompt sans rien dire. Trois
propriétés :

- **La même session continue** (`resume`), ce n'est pas un redémarrage à zéro — le travail déjà fait
  et le contexte sont là. C'est le chemin déjà existant des reprises après coupure réseau qui est
  réutilisé, en remplaçant simplement « la cause de l'échec » par « un humain a interrompu » et
  `resume_prompt` par ce que l'humain a dit.
- **Ça ne consomme pas de `max_attempts`.** Ce quota est fait pour les pannes, pas pour les humains.
- **C'est coopératif** : la coupure se fait à une frontière de message, la tâche n'est pas annulée de
  force. Le prix est un délai jusqu'au message suivant (si un subagent tourne, il faut attendre son
  retour) ; en échange, l'état n'est pas déchiré en plein milieu.

Disons le coût franchement : une interruption fait **perdre au subagent en vol son travail à moitié
fait** (mesuré lors de la coupure réseau HT001, voir
[issue #2](https://github.com/ChenyuHeee/flower/issues/2)). L'implémentation de référence du terminal
l'écrit noir sur blanc dans son message d'aide, pour que l'humain le sache avant d'appuyer ; votre
UI devrait faire pareil.

Si vous ne voulez pas interrompre mais seulement ajouter une exigence, passez par l'inbox
(`ch.send(...)`) — elle n'interrompt rien, et le délai est le prochain point de contrôle de l'agent.

### Oracle : poser une question sans déranger le run {#旁路顾问问一句而不打扰运行}

Pour savoir « où on en est », inutile d'interrompre, et il ne faut pas demander au coordinateur :
cet échange **occuperait à jamais le contexte du thread principal** (qui contient des décisions, pas
un journal de questions-réponses), et il devrait lâcher ce qu'il est en train de faire. Sur un run
de dix heures, trois questions posées en passant suffisent à payer ces deux coûts.

L'[oracle](../reference/glossary.md#旁路顾问) est une dérivation en lecture seule. Il n'a que
`Read` / `Glob` / `Grep`, le workbench est ouvert, et il est bridé par défaut : `max_turns=12`,
`max_budget_usd=0.5`. Dans le terminal, une ligne commençant par `?` le déclenche ; il répond à
partir de deux choses : la fenêtre d'événements récents (60 entrées fixes) et le brief, les
objectifs, les notes et les livrables présents dans le workbench. Il utilise son propre `Runtime`
(`<run_dir>/aside`), si bien que son coût et le [lignage](../reference/glossary.md#血缘) de sa
session **ne se mélangent pas au manifeste principal** — ce manifeste consigne « quelles étapes ce
run a exécutées », et une question posée en passant n'est pas une étape.

Mesuré : deux questions pour $0.5190 au total, et pas un octet de plus dans le manifeste du run
principal.

### Deux règles dures {#两条硬规矩}

!!! warning "on_event ne doit ni bloquer, ni laisser échapper d'exception"
    **Un : `on_event` est une fonction synchrone, appelée dans le thread de la boucle d'événements.**
    Donc `asyncio.Queue.put_nowait()` est sûr, `await` ne l'est pas (ce n'est pas une coroutine), et
    **la bloquer, c'est bloquer le run entier**. Pour du travail lent, déposez dans une file et
    laissez une autre tâche s'en occuper.

    **Deux : une exception levée dans `on_event` abîme le run lui-même.** Les événements de texte
    sont émis dans le bloc `try` de `Runtime._attempt` : l'exception est enregistrée dans
    `result.error` — l'étape est déclarée en échec. Les événements `retry` sont émis en dehors : là,
    l'exception remonte directement hors de `Runtime.run`. Le front-end ne doit pas emporter trois
    heures de travail : **enveloppez votre callback dans un `try`.**

    Exception : les événements `ask` émis par `HumanChannel` lui-même sont déjà enveloppés ; les
    exceptions sont collectées dans `channel.ui_errors` et n'interrompent pas le run.

## Quand ne pas s'en servir {#什么时候不该用它}

### Ce qu'il ne faut pas faire dans la couche d'interaction {#交互层里不该做的事}

| À ne pas faire | Pourquoi | À faire à la place |
|---|---|---|
| `from claude_agent_sdk import ...` | Dès que la couche d'interaction dépend des types du SDK, une montée de version du SDK oblige le front à suivre : cette couche n'aura servi à rien | N'utiliser que `kind` / `text` / `tool` / `payload` d'`Event` |
| Lire `ev.raw` | Idem, et en plus ce n'est pas sérialisable en JSON | S'il manque un détail, ajoutez-le au `payload` dans `normalize()`, ne contournez pas la frontière |
| `await`, requêtes réseau ou écritures disque lentes dans `on_event` | C'est synchrone, appelé dans le thread de la boucle d'événements ; la bloquer, c'est bloquer le run entier | `put_nowait()` dans une file, consommée par une autre tâche |
| Laisser `on_event` lever une exception | Pour les événements de texte, l'exception devient `result.error` et l'étape est en échec | Envelopper tout le corps du callback dans un `try` |
| Couper les questions avec `disallowed_tools` | C'est **au niveau de la session** : ça désactive aussi l'outil du même nom chez les subagents (message d'erreur observé : `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` ou `timeout_s=0` |
| Retirer `mcp__human__ask` d'`allowed_tools` en croyant interdire les questions | `allowed_tools` n'est pas exclusif : c'est une liste de pré-approbation, pas une liste blanche ; brancher un `channel` donne les deux outils ensemble | Idem ci-dessus |
| Reconstruire soi-même le chemin vers `需求.md` / `目标.md` | Le workbench peut être à deux endroits ; se tromper ne lève aucune erreur, ça échoue silencieusement | `wake_state()` ou `wf.workbench` |
| Reconstituer progression et résultats depuis le flux d'`Event` | Le texte est découpé en plusieurs morceaux par les handoffs et les reprises | `on_step(step, result)`, qui donne le `StepResult` complet |
| `timeout_s=None` en mode sans surveillance | Personne ne répond, le run reste suspendu pour toujours, sans erreur ni timeout | `0`, ou un nombre fini de secondes |

### Quand il n'y a carrément rien à changer {#什么时候根本不用换}

- **Vous voulez juste changer les couleurs, afficher une ligne de plus ou de moins** — modifiez la
  fonction de rendu, ça suffit. Réécrire l'interruption, l'oracle, les accusés de réception de
  l'inbox, le sauvetage sur SIGHUP / SIGTERM et l'attente de la fin de la dérivation avant de
  quitter, tout cela présent dans l'implémentation de référence terminal, coûte cher.
- **Vous voulez juste exécuter une étape, sans interaction** — utilisez `flower once`. Il ne passe
  pas par le pilote interactif : il n'a de toute façon ni interruption par Ctrl+C, ni thread de
  réponse sur l'entrée standard, ni oracle, ni sauvetage sur signal.
- **Ce que vous voulez changer, c'est en fait le workflow, pas l'UI** — voir
  [Concevoir un workflow](workflow.md). La couche d'interaction décide seulement qui regarde et qui
  répond ; le nombre d'étapes, la manière de juger et le moment de sortir plus tôt, c'est `Workflow`
  qui les décide.
- **Ce que vous voulez changer, c'est le stockage de sessions, le modèle ou le budget** — ces trois
  choses ne sont pas sur cette frontière, voir la [référence de l'API Python](../reference/api.md).
