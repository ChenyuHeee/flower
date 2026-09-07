# Continuité

Relancer `flower` dans le même répertoire, et il reprend la conversation là où elle s'était arrêtée — processus tué, terminal planté, machine redémarrée, c'est pareil. Vous n'avez pas besoin de connaître le mot session, ni de retenir le moindre id. Cette page explique sur quoi ça repose, quand ça échoue en silence, et comment ne *pas* reprendre volontairement.

!!! note "Continuité n'est pas handoff"
    La [continuité](../reference/glossary.md#接续) est **inter-processus** : le processus suivant reprend le [run](../reference/glossary.md#运行) précédent.
    Le [handoff](../reference/glossary.md#换代) est **interne à un même run** : le contexte est presque plein, la [session](../reference/glossary.md#会话) courante
    écrit un [document de handoff](../reference/glossary.md#交接书) et une nouvelle session prend la suite — voir [Handoff](handoff.md).

    Les deux s'emboîtent automatiquement, sans câblage supplémentaire : le [lignage](../reference/glossary.md#血缘) retient toujours la **dernière**
    session ayant pris le relais pour cette étape, donc le réveil suivant reprend celle du successeur.

## Quel problème ça résout

Tout est en fait sur le disque. `runs/sessions.db` contient le transcript **complet** de chaque session historique, `需求.md` / `目标.md`
sont des artefacts gelés, et le code est dans l'espace de travail.

**Ce qui est perdu, c'est une seule ligne de correspondance** — « quelle étape a utilisé quelle session ». Elle ne vivait qu'en mémoire, dans `ctx["_sessions"]`,
et disparaissait à la sortie du processus. Le nouveau processus démarre donc avec un [coordinateur](../reference/glossary.md#协调者) amnésique : qui il a délégué,
quelles impasses il a explorées, pourquoi il a écarté telle approche — tout est refait de zéro.

Dans [HT002](../cases/ht002.md), il a passé une heure à tester des flags de compilation. Changez de processus, et cette heure est perdue.

## Comment s'en servir (code minimal)

Rien à configurer en ligne de commande, la continuité est activée par défaut sur ce chemin `flower` :

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # première fois
# …ça se termine, ou vous faites Ctrl-C et vous partez, ou la machine redémarre

cd ~/proj && flower "顺便支持代码块高亮"          # reprend la conversation précédente
cd ~/proj && flower                              # ne rien dire = continuer
cd ~/proj && flower --new "另一件事"              # cette fois, ne pas reprendre
```

Quand vous écrivez votre propre [workflow](../reference/glossary.md#流程), la continuité est aussi activée par défaut — la valeur par défaut de `Workflow.continuous` est
`True` :

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous vaut True par défaut
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # numéro du réveil, 1 à la première exécution
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

À la deuxième exécution de ce code dans le même répertoire, `ctx["_woke"]` vaut `2`, et `ctx["_sessions"]["取词"]` est
**le même id** qu'à la première — l'étape 取词 a repris la session précédente au lieu d'en ouvrir une nouvelle.

!!! tip "Juste savoir si ce répertoire est reprenable"
    `wake_state()` est une sonde en lecture seule, elle **n'écrit pas un seul octet** :

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Renvoie `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = le brief existe et ses quatre sections sont complètes ;
    `checks` = nombre d'entrées dans la liste de vérification ; `woke` = nombre de réveils déjà effectués ; `steps` = correspondance nom d'étape → session_id.
    C'est là-dessus que la ligne de commande décide si l'invite doit demander « que faire » ou « continuer ».

## Ce que ça fait réellement

### Les trois fichiers posés sur le disque

`run_dir` vaut `./runs` par défaut, **relatif au répertoire de travail courant, pas au workspace**.

| Chemin | Contenu |
|---|---|
| `runs/lineage.json` | Le lignage : `{"workspace": "…", "woke": N, "steps": {"nom d'étape": "session_id"}}`. Toute la continuité repose dessus |
| `runs/sessions.db` | SQLite, transcripts intégraux. Tables `entries` / `meta` / `summaries`, clé `project_key/session_id[/subpath]` — les transcripts de subagents sont stockés à part via subpath |
| `runs/manifest.json` | Tableau JSON, manifeste de run **cumulé entre processus**. Une ligne par étape, seul endroit où retrouver un session_id après coup |

Le fichier de lignage ressemble à ceci :

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Chaque ligne de `manifest.json` contient tous les champs de `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — plus, ajoutés à la main, `duration_s` (c'est une `@property`, `asdict()` ne la récupère pas) et
`run` (marqueur de processus, `YYYYmmdd-HHMMSS-<6 位 hex>`).

Le nom d'étape y prend quatre formes, qui montrent d'un coup d'œil comment l'étape s'est déroulée : `<步骤名>` (première tentative),
`<步骤名>#retry<N>` (retry ordinaire), `<步骤名>#round<N>` (verdict négatif, renvoyé pour poursuite),
`<步骤名>·判定#<N>` (le round du [juge](../reference/glossary.md#判定者)).

L'écriture est **en append, pas en écrasement** : à chaque écriture le fichier est relu, la déduplication se fait sur le champ `run` — les lignes de ce processus sont remplacées par les plus récentes,
celles des autres sont laissées telles quelles. Faire tourner plusieurs flower en parallèle dans le même répertoire est donc sûr.

### `continuous=True` change la sémantique de `resume_from`

C'est le point le plus facile à manquer : `Workflow.continuous` vaut `True` par défaut, donc `resume_from=None`
**ne signifie pas « nouvelle session »**.

| Écriture | Dans le même run | Entre processus (`continuous=True`) |
|---|---|---|
| `resume_from=None` (défaut) | Nouvelle session, uniquement le contexte passé dans le prompt | **Reprend la session de l'étape de même nom dans le lignage** |
| `resume_from="nom de l'étape précédente"` | Reprend la même session, contexte complet | Idem |
| `resume_from=…, fork=True` | Fork, sans polluer la session d'origine | Idem |

Pour avoir une session neuve à chaque processus, il faut écrire explicitement `Workflow(..., continuous=False)`.

Au chargement du lignage il y a une vérification supplémentaire : chaque `(nom d'étape, session_id)` relu passe d'abord par `runtime.has_session(sid)`
pour confirmer qu'il est toujours dans `sessions.db` ; on ne l'utilise que s'il est vivant. La raison : le fichier de lignage peut survivre à `sessions.db`,
et un resume sur une session inexistante n'explose qu'une fois le sous-processus démarré.

!!! warning "Le nom d'étape est la clé stable entre processus"
    Le lignage est indexé par `Step.name`. **Changer le nom d'une étape revient à couper le lignage** — sans erreur, simplement une session neuve au run suivant.
    Les noms suffixés (`#retry`, `#round`, `·判定#`) n'entrent pas dans le lignage, `Lineage.remember` utilise toujours le nom d'origine.

### Deux invariants

**Un. On écrit sur disque dès qu'on a le session_id, sans attendre la fin de l'étape.**

Un processus tué de force est précisément le scénario à couvrir. Vécu en vrai : le 2026-09-07, Terminal.app a planté deux fois, le noyau a envoyé SIGHUP,
et l'action par défaut de SIGHUP est la terminaison immédiate — pas une ligne de `finally` ne s'exécute. À l'époque le lignage était écrit **aux frontières d'étape**,
donc le run mort à l'intérieur de la première étape avait un `steps` vide, et l'humain devait répondre à nouveau à des questions déjà répondues (voir issue #6).

Aujourd'hui `Runtime.on_session` écrit sur disque à l'instant même où l'id arrive — en pratique au plus tôt au premier message assistant,
le message système init ne portant pas de `session_id` dans le SDK Python. L'écriture passe d'abord par un `.tmp` puis un remplacement atomique,
une mort en cours de route ne laisse pas de demi-fichier ; un échec d'écriture (`OSError`) est avalé en silence et n'emporte pas le run.

Ce hook **ne couvre que l'appel `runtime.run`** ; il est retiré avant le gate via `try/finally`. Le juge utilise le même
`Runtime` : s'il était encore attaché, sa session serait écrite dans le lignage de l'étape de travail.

**Deux. Si ça ne correspond pas, on considère que ça n'existe pas, sans erreur.**

Trois façons de ne pas correspondre : le chemin de l'espace de travail a changé (répertoire copié ailleurs — [HT001](../cases/ht001.md) a justement été extrait d'un conteneur),
la session n'est plus en base (`sessions.db` supprimé), le fichier de lignage est corrompu. Dans tous les cas, retour silencieux à « repartir de zéro ».

Le champ `workspace` sert de garde : le `project_key` du SDK est dérivé du chemin de l'espace de travail (`/`, `_`, `.` remplacés par `-`),
et après copie du répertoire, l'ancien session_id est introuvable au nouvel emplacement — donc chemin qui ne correspond pas = inexistant.

**La continuité est un bonus, sa défaillance ne doit pas empêcher de travailler.**

### Processus tué, et redémarrage machine

Les deux cas donnent le même résultat — ça reprend — mais le déroulé diffère :

| Situation | Ce qui se passe | Run suivant |
|---|---|---|
| `Ctrl-C` une fois | Interruption coopérative, coupure propre à une **frontière de message**. On peut au passage dire quelque chose, le même processus reprend la même session et continue. Une interruption ne compte pas comme tentative échouée, elle ne consomme pas de quota de retry | Ne concerne pas la continuité |
| `Ctrl-C` deux fois | Lève directement `KeyboardInterrupt` et sort. La clôture se limite à fermer le store, **l'étape en vol n'entre pas dans `manifest.json`** | Le lignage est déjà sur disque, ça reprend |
| `SIGTERM` / `SIGHUP` | Le handler appelle d'abord `rescue()`, ce qui écrit aussi l'étape en vol dans `manifest.json` (marquée `error="killed-by-signal"`), puis restaure l'action par défaut et part vraiment | Idem, ça reprend |
| `SIGKILL`, coupure de courant, redémarrage machine | Aucune clôture | Ça reprend quand même — les trois fichiers sont sur disque, le lignage est écrit à l'instant où l'id arrive |

Une seule condition : **même `workspace` et même `run_dir`**. `run_dir` est relatif au répertoire de travail courant,
donc lancer `flower` depuis un autre répertoire cherchera un autre `runs/`, et ne reprendra pas.

### Le juge est toujours une session neuve

C'est **garanti par construction**, pas par mémoire.

Le juge n'est pas un `Step` — il est délégué directement par `rt.run()` dans le gate de `with_goal`
(voir [Gardien d'objectif](goal.md)), il ne passe jamais par le chemin du lignage. Il est donc, à chaque round et à chaque réveil, une paire d'yeux entièrement neuve.

C'est là toute sa valeur : **il ne sait pas combien de fois l'exécutant a essayé ni à quel point ça a été pénible, donc il ne lui cherche pas d'excuses.**
Le faire suivre la continuité dégraderait le gardien d'objectif en auto-audit.

La section 4 de `tests/lineage_offline.py` verrouille ce point.

### La phrase dite au réveil doit atterrir à trois endroits

`flower "顺便支持代码块高亮"` dans un répertoire déjà utilisé, ce **n'est pas une nouvelle tâche, c'est une phrase de plus**.
Elle fait trois choses à la fois — s'il en manque une, l'échec est silencieux :

| Où ça atterrit | Conséquence si ça manque |
|---|---|
| Ajouté à `需求.md` (`## 唤醒时追加`) | Ne survit pas à la frontière d'étape. L'étape suivante est une nouvelle session, qui ne lit que les artefacts gelés |
| Utilisé comme prompt de l'étape de travail | Le coordinateur ne le reçoit tout simplement pas |
| **Déclenche une re-dérivation de `目标.md`** | Le juge lit encore l'ancienne liste, **ce qui vient d'être ajouté n'entre pas du tout dans le verdict** |

Le troisième point est le plus facile à oublier. Le juge ne lit que le `目标.md` gelé, il ne voit pas ce que vous avez ajouté en cours de route — sans re-dérivation il déclarera
« atteint » selon l'ancienne liste, alors que la chose que vous vouliez n'a jamais été vérifiée. Le coût : une exécution supplémentaire de 设定目标 à chaque ajout ([HT002](../cases/ht002.md) mesuré à
$0.41 / 3 minutes).

**Un réveil sans rien dire** (entrée directe) n'ajoute rien, ne re-dérive rien, et ne coûte pas un centime de plus.

### Un plantage à l'intérieur de la première étape (确认需求) est aussi reprenable

`clarify_step` embarque un `resume_prompt` (constante `CLARIFY_RESUME`) : en cas de plantage pendant la clarification, au redémarrage
on dit au [clarificateur](../reference/glossary.md#确认者) « 接着刚才那次没问完的需求确认继续 ——
不是重新开始 », plutôt que de renvoyer la demande initiale comme une nouvelle tâche. Combiné à l'invariant « écrire dès qu'on a le session_id »,
un run mort dans la première étape, avec `需求.md` pas encore gelé, est désormais reprenable sans avoir à répondre à nouveau.

Inversement, les étapes préalables déjà gelées sont **entièrement sautées** : si les quatre sections de `需求.md` sont complètes, 确认需求 est sautée (mais son contenu est tout de même injecté dans ctx),
et si `目标.md` est complet, 设定目标 est sautée.

### À la reprise, ce n'est pas la même phrase qui est envoyée

C'est le rôle de `Step.resume_prompt`. L'interlocuteur a **déjà** dans son contexte le brief, l'objectif, et où il en était — lui renvoyer tel quel
« fais selon ce brief : <brief intégral> » n'est que du bruit, et pire, ça peut se lire comme « le besoin a changé, relis tout ».

Sans `resume_prompt`, on retombe sur `prompt` — certaines étapes doivent effectivement renvoyer le texte intégral (quand 设定目标 re-dérive la liste,
c'est précisément le brief complet qu'il lui faut).

### Au réveil, une ligne de rapport d'abord

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sans ce rapport, « est-ce qu'il se souvient ou pas » est totalement imperceptible — et c'est précisément toute la valeur de cette couche. Dans le bandeau,
`需求已确认` est toujours présent, `目标 N 条` seulement si la liste de vérification n'est pas vide, et `干活上下文 X` suppose de pouvoir retrouver dans `sessions.db`
la taille de contexte du dernier tour de cette session.

**Ce chiffre de contexte est affiché délibérément** — la raison est dans la section « Coût » plus bas.

### Résilience : attendre quand le réseau tombe, et ne pas laisser les erreurs entrer dans le contexte repris

La [résilience](../reference/glossary.md#韧性) va de pair avec la continuité : sur plusieurs heures d'exécution, le réseau tombera forcément une fois, et le comportement par défaut est mauvais —
à l'instant de la coupure, le harness insère dans le transcript un **message assistant synthétique** (`isApiErrorMessage=true`,
`model="<synthetic>"`), dont le corps est « API Error: Can't reach the API server … ». Ce message devient la feuille de la session,
et au resume il est réinjecté comme « la dernière chose que le modèle a dite » — le modèle croit alors discuter d'une panne réseau.

`Resilience` fait trois choses :

**Un. La sonde ne fait que DNS + TCP.** `reachable(host, port, timeout=5.0)` n'exécute qu'un `getaddrinfo` plus une poignée de main TCP,
**sans HTTP, sans identifiants, sans coût** ; toute exception compte comme injoignable. L'adresse sondée est décidée par `endpoint()`, qui suit
`ANTHROPIC_BASE_URL`, par défaut `https://api.anthropic.com`, port `443` par défaut (`80` en http).
**Avec une passerelle auto-hébergée, il faut sonder la passerelle** — `api.anthropic.com` joignable ne dit rien de la passerelle.

**Deux. Distinguer ce qu'il faut attendre de ce qu'il faut arrêter.** `classify(text)` renvoie `"transient"` / `"fatal"` / `"unknown"`,
**fatal est testé avant transient** — les textes de type 401 contiennent souvent le mot « connection », et dans l'ordre inverse on attendrait indéfiniment.
Valeurs par défaut : `max_attempts=6` (première tentative comprise), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 heure), `retry_unknown=True`.
Le backoff est `min(base_delay * 2**(attempt-1), max_delay)`, multiplié par un jitter de ±25%.

Si un session_id a déjà été obtenu, on **reprend la session plutôt que de tout refaire**, les dépenses antérieures ne sont pas perdues. À la reprise, ce qui est envoyé est
`Resilience.resume_prompt` : « 上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,
从中断处接着做,不要重头来过。 » Il **ne contient volontairement aucun détail d'erreur** — le modèle doit savoir « tu as été interrompu, continue »,
pas s'il s'agissait d'un ENOTFOUND ou d'un 503.

**Trois. Les erreurs produites par la tempête de retries n'entrent pas dans le contexte après resume.** C'est le travail du [prune](../reference/glossary.md#剪除).
Le session store de `Runtime` est câblé en dur sur `PruningSessionStore`, qui fait trois choses au `load()` :

- Retirer les messages d'erreur API synthétiques. **Conservés tels quels dans SQLite**, simplement pas réinjectés
- Retirer les appels refusés trop anciens, ne garder que les `keep_denials=1` plus récents
- Remplacer les `tool_result` résiduels d'une interruption par une note neutre « [上一轮在此处被中断,该工具结果未产生] », en remplaçant seulement le corps, sans retirer l'entrée

Garder 1 plutôt que 0 a une raison : un appel refusé n'a jamais été exécuté, son résultat ne contient pas d'information, mais il occupe une place non négligeable
(mesuré une fois à 273 caractères = 93 caractères de refus + 180 caractères de **texte intégral de la commande morte**), et **il induit en erreur** —
en pratique, après avoir lu quelques « 不直接使用 Bash », le coordinateur cessait même d'essayer un `git status` pourtant autorisé : impuissance apprise.

Mais garder la plus récente est utile : ça évite que le modèle réessaie en boucle la même commande bloquée dans le même tour.

Le retrait a une ligne rouge structurelle : le transcript est une chaîne simple via `parentUuid` ; retirer une entrée oblige à rattacher ses enfants à l'ancêtre vivant le plus proche,
sinon la chaîne casse là et tout l'historique antérieur est perdu.

[HT001](../cases/ht001.md) a rencontré le cas une fois en conditions réelles : coupure réseau de 01:52:40 → 01:55:41, l'étape correspondante dans `manifest.json` porte
`attempts=2` / `resumed=True` / `ok=True`, et après reprise elle a tourné plus de 8 heures jusqu'à l'achèvement.

Dernier point sujet à malentendu : **`Runtime(trim=False)` ne veut pas dire « on ne nettoie rien »**. `trim` vaut `False` par défaut,
mais il ne désactive que la couche de **[trim](../reference/glossary.md#裁剪) des gros résultats d'outils**. Retirer les résidus de coupure, retirer les appels refusés,
neutraliser les résidus d'interruption, marquer comme périmés les résultats de [commandes éphémères](../reference/glossary.md#一次性命令) — ces quatre choses restent faites
(`ephemeral` vaut `True` par défaut, `keep_denials` vaut `1` par défaut).

### Coût : le contexte ne fait que monter, sans fin

C'est le coût intrinsèque de la continuité, pas un bug.

L'étape 干活 de [HT001](../cases/ht001.md) a tourné 10.44 heures d'affilée ; le contexte du [thread principal](../reference/glossary.md#主线程) était de
**28.7K** au tour 1, **35.2K** au tour 20, **108.6K** au tour 35, **158.2K** au tour 50, **185.9K** au tour 70,
monotone croissant, avec une pente d'environ **2.2K/tour** ; aucune compaction sur tout le run, **18.6%** de la fenêtre de 1M consommés. En extrapolant cette pente,
le mur arrive vers **440 tours** — la limite du « long-horizon » sous sa forme actuelle est environ **6 fois** ce run. Une continuité permanente signifie qu'un jour on touchera la fenêtre.

Deux mécanismes gèrent ça :

1. **Le trim** (`flower --no-trim` pour le désactiver, activé par défaut sur ce chemin `flower`) — au resume, les vieux gros résultats d'outils sont remplacés par
   des pointeurs de fichiers ; le contenu n'est pas perdu, il n'est simplement plus résident
2. **Le [handoff](handoff.md)** — au seuil, on écrit un document de passation et on change de session. **Ce n'est pas de la [compaction](../reference/glossary.md#压缩)** :
   le document est lisible et modifiable, vous voyez ce qui a été perdu. Le contexte redescend donc périodiquement au lieu de monter jusqu'au mur

**D'où l'obligation d'afficher le chiffre de contexte dans la ligne de réveil** : si l'humain le voit, il a une chance de décider lui-même de repartir avant le mur.

Au passage : `--rounds` (nombre total de rounds de travail) **est remis à zéro à chaque réveil**. C'est intentionnel — un nouveau réveil est une nouvelle intention,
il n'a pas à hériter des rounds consommés la fois précédente.

### Repartir sur autre chose

```bash
flower --new "另一件事"
```

Ou taper directement `/new` à l'invite de réveil :

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**On archive, on ne supprime pas.** `lineage.json`, `需求.md` et `目标.md` sont **déplacés ensemble** vers `notes/archive/<YYYYmmdd-HHMMSS>/`,
et les champs `steps` et `woke` du lignage sont remis à zéro en même temps. Ces trois éléments sont trois faces d'un même historique ; n'en ranger qu'une partie laisserait un état bancal du genre
« l'objectif est encore là mais la conversation a disparu ».

`sessions.db` n'est pas touché — c'est l'archive, chaque transcript y reste consultable.

Côté code, cela correspond à `Lineage.archive(into, extra=[...])`.

## Quand ne pas s'en servir

- **Les cas qui exigent un point de départ propre à chaque fois.** Exécuter le même workflow en lot, faire une évaluation comparative, reproduire un bug pour quelqu'un —
  rien de tout ça ne doit traîner le contexte précédent. Écrivez `Workflow(..., continuous=False)`, ou changez de `run_dir` à chaque fois.
- **Le répertoire va être déplacé ou copié, ou `run_dir` n'est pas persistant.** Tourner dans un conteneur avec `runs/` sur le système de fichiers interne du conteneur,
  ou rsyncer l'espace de travail vers une autre machine — la continuité **échoue en silence** (la garde sur le chemin rejette un lignage qui ne correspond pas),
  ne comptez pas dessus comme sur une garantie.
- **C'est une nouvelle intention et le contexte est déjà gros.** La continuité vous fait porter tout un historique sans rapport, et vous payez des tokens pour lui à chaque tour.
  Plutôt que de subir, faites `--new` : archiver et repartir.
- **Un agent unique jetable.** `flower once` ne passe pas par `Workflow`, il n'a pas de lignage ; pour reprendre, il faut passer soi-même `--resume <session_id>`.
- **Prendre la continuité pour une sauvegarde.** Elle ne retient que « quelle étape a utilisé quelle session ». Le code, les livrables et les décisions doivent atterrir dans l'espace de travail et le
  [workbench](../reference/glossary.md#工作台), on ne doit pas espérer les déterrer du transcript.

## Voir aussi

- [Handoff](handoff.md) — que faire quand le contexte est plein à l'intérieur d'un même run ; c'est la même chose vue dans l'autre sens
- [Gardien d'objectif](goal.md) — pourquoi le juge ne reprend pas
- [Économie du contexte](context.md) — ce que gèrent respectivement le trim, le prune et le spill
- [API Python](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Ligne de commande](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Sources : [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
