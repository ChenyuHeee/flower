# Continuité

Relancez `flower` dans le même répertoire : il reprend la conversation là où elle s'était arrêtée — processus tué, terminal planté, machine redémarrée, c'est pareil. Vous n'avez pas besoin de connaître le mot session, ni de retenir le moindre id. Cette page explique sur quoi cela repose, quand cela échoue silencieusement, et comment ne *pas* reprendre volontairement.

!!! note "Continuité n'est pas passation"
    La [continuité](../reference/glossary.md#接续) est **inter-processus** : le prochain processus reprend l'[exécution](../reference/glossary.md#运行) précédente.
    La [passation](../reference/glossary.md#换代) se joue **à l'intérieur d'une même exécution** : le contexte est presque plein, la [session](../reference/glossary.md#会话) courante
    écrit un [document de passation](../reference/glossary.md#交接书), une nouvelle session prend le relais — voir [Passation](handoff.md).

    Les deux s'emboîtent automatiquement, aucun câblage supplémentaire : le [lignage](../reference/glossary.md#血缘) retient toujours la **dernière**
    session ayant pris le relais sur cette étape, donc le prochain réveil reprend chez le successeur.

## Quel problème cela résout {#解决什么问题}

Sur le disque, tout est déjà là. `runs/sessions.db` contient le transcript **complet** de chaque session historique, `需求.md` / `目标.md`
sont des pièces gelées, le code est dans l'espace de travail.

**La seule chose perdue, c'est une ligne de correspondance** — « quelle étape a utilisé quelle session ». Elle ne vivait qu'en mémoire, dans `ctx["_sessions"]`,
et disparaissait à la sortie du processus. Au démarrage suivant, le [coordinateur](../reference/glossary.md#协调者) était un nouveau venu amnésique : qui il avait délégué,
quelles impasses il avait essayées, pourquoi il avait écarté telle approche — tout était à refaire.

Dans [HT002](../cases/ht002.md), il a passé une heure à tester des flags de compilation. Changez de processus, cette heure est perdue.

## Comment l'utiliser (code minimal) {#怎么用最小代码}

En ligne de commande, rien à configurer : sur ce chemin, `flower` a la continuité activée par défaut :

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # première fois
# …terminé, ou vous faites Ctrl-C et vous partez, ou la machine redémarre

cd ~/proj && flower "顺便支持代码块高亮"          # reprend la conversation précédente
cd ~/proj && flower                              # ne rien dire = continuer
cd ~/proj && flower --new "另一件事"              # cette fois, ne pas reprendre
```

Quand vous écrivez votre propre [workflow](../reference/glossary.md#流程), la continuité est également active par défaut — `Workflow.continuous` vaut
`True` par défaut :

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
**le même id** qu'à la première fois — l'étape « 取词 » a repris la session précédente au lieu d'en ouvrir une nouvelle.

!!! tip "Juste savoir si ce répertoire peut être repris"
    `wake_state()` est une sonde en lecture seule, elle **n'écrit pas un seul octet** :

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Elle renvoie `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = le brief existe et ses quatre sections sont complètes ;
    `checks` = nombre d'entrées de la liste de vérification ; `woke` = nombre de réveils déjà effectués ; `steps` = correspondance nom d'étape → session_id.
    C'est là-dessus que la ligne de commande décide si l'invite demande « que faire ? » ou « continuer ? ».

## Ce que cela fait réellement {#它实际做了什么}

### Les trois fichiers posés sur le disque {#落在磁盘上的三个文件}

`run_dir` vaut `./runs` par défaut, **relatif au répertoire de travail courant, pas au workspace**.

| Chemin | Contenu |
|---|---|
| `runs/lineage.json` | Lignage : `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Toute la continuité repose dessus |
| `runs/sessions.db` | SQLite, transcripts intégraux. Tables `entries` / `meta` / `summaries`, clé `project_key/session_id[/subpath]` — les transcripts des subagents sont rangés à part via subpath |
| `runs/manifest.json` | Tableau JSON, manifeste d'exécution **cumulé entre processus**. Une ligne par étape, seul endroit pour retrouver un session_id après coup |

Le fichier de lignage ressemble à ceci :

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Chaque ligne de `manifest.json` reprend tous les champs de `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — plus deux champs ajoutés à la main : `duration_s` (c'est une `@property`, `asdict()` ne la voit pas) et
`run` (marqueur de processus, `YYYYmmdd-HHMMSS-<6 位 hex>`).

Le nom d'étape y prend quatre formes, qui montrent d'un coup d'œil comment l'étape s'est terminée : `<步骤名>` (première tentative),
`<步骤名>#retry<N>` (nouvelle tentative ordinaire), `<步骤名>#round<N>` (verdict négatif, renvoyé pour continuer),
`<步骤名>·判定#<N>` (le tour du [juge](../reference/glossary.md#判定者)).

L'écriture **ajoute sans écraser** : à chaque écriture, le fichier est relu et dédupliqué sur le champ `run` — les lignes de ce processus sont remplacées par les plus récentes,
celles des autres restent intactes. Faire tourner plusieurs flower en parallèle dans le même répertoire est donc sûr.

### `continuous=True` change la sémantique de `resume_from` {#continuoustrue-改变了-resume_from-的语义}

C'est le point le plus facile à manquer : `Workflow.continuous` vaut `True` par défaut, donc `resume_from=None`
**ne signifie pas « session neuve »**.

| Écriture | Dans la même exécution | Entre processus (`continuous=True`) |
|---|---|---|
| `resume_from=None` (défaut) | Nouvelle session, seulement le contexte passé dans le prompt | **Reprend la session de l'étape de même nom dans le lignage** |
| `resume_from="上一步名"` | Reprend la même session, contexte complet | Idem |
| `resume_from=…, fork=True` | Fork, sans polluer la session d'origine | Idem |

Pour repartir d'une session neuve à chaque processus, il faut écrire explicitement `Workflow(..., continuous=False)`.

Au chargement du lignage, une vérification supplémentaire a lieu : chaque `(nom d'étape, session_id)` relu passe d'abord par `runtime.has_session(sid)`
pour confirmer qu'il est toujours dans `sessions.db` ; on ne l'utilise que s'il est vivant. Raison : le fichier de lignage peut survivre à `sessions.db`,
et reprendre une session inexistante n'explose qu'une fois le sous-processus démarré.

!!! warning "Le nom d'étape est la clé stable entre processus"
    Le lignage est indexé par `Step.name`. **Changer un nom d'étape revient à couper le lignage** — aucune erreur, simplement une session neuve à la prochaine exécution.
    Les noms suffixés (`#retry`, `#round`, `·判定#`) n'entrent pas dans le lignage ; `Lineage.remember` utilise toujours le nom d'origine.

### Deux invariants {#两条不变式}

**Un. Dès que le session_id est connu, il est écrit sur disque, sans attendre la fin de l'étape.**

Le processus tué brutalement est exactement le scénario à couvrir. Vécu en vrai : le 2026-09-07, Terminal.app a planté deux fois, le noyau a envoyé SIGHUP,
et l'action par défaut de SIGHUP est de terminer immédiatement — pas une ligne de `finally` ne s'exécute. À l'époque, le lignage était écrit **aux frontières d'étape** ;
l'exécution morte à l'intérieur de la première étape avait donc un `steps` vide, et l'utilisateur a dû répondre une seconde fois à des questions déjà répondues (voir issue #6).

Aujourd'hui, `Runtime.on_session` écrit sur disque à l'instant même où l'id arrive — en pratique dès le premier message assistant,
car le message système init ne porte pas de `session_id` dans le SDK Python. L'écriture passe par un `.tmp` puis un remplacement atomique,
une mort en cours de route ne laisse pas de fichier à moitié écrit ; un échec d'écriture (`OSError`) est avalé silencieusement et n'emporte pas l'exécution.

Ce hook **ne couvre que la ligne `runtime.run`** ; il est retiré avant le gate via `try/finally`. Le juge utilise le même
`Runtime` — s'il était encore accroché, sa session serait inscrite dans le lignage de l'étape de travail.

**Deux. Si ça ne correspond pas, on fait comme si de rien n'était, sans erreur.**

Trois façons de ne pas correspondre : le chemin de l'espace de travail a changé (répertoire copié ailleurs — [HT001](../cases/ht001.md) a justement été sorti d'un conteneur),
la session n'est plus dans la base (`sessions.db` supprimé), le fichier de lignage est corrompu. Dans tous les cas, retour silencieux à « repartir de zéro ».

Le champ `workspace` sert de garde : le `project_key` du SDK est dérivé du chemin de l'espace de travail (`/`, `_`, `.` deviennent tous `-`) ;
après une copie de répertoire, un ancien session_id est tout simplement introuvable au nouvel emplacement, donc un chemin qui ne correspond pas est traité comme absent.

**La continuité est un bonus ; sa défaillance ne doit pas empêcher de travailler.**

### Processus tué, et machine redémarrée {#进程被杀和机器重启}

Le résultat est le même — ça reprend — mais le déroulé diffère :

| Situation | Ce qui se passe | Prochaine exécution |
|---|---|---|
| `Ctrl-C` une fois | Interruption coopérative, coupure propre à une **frontière de message**. On peut au passage dire un mot, et reprendre la même session dans le même processus. Une interruption ne compte pas comme tentative échouée, elle ne consomme pas de quota de retry | Ne concerne pas la continuité |
| `Ctrl-C` deux fois | Lève directement `KeyboardInterrupt` et sort. La clôture se limite à fermer le stockage, **l'étape en vol n'entre pas dans `manifest.json`** | Le lignage était déjà sur disque, ça reprend |
| `SIGTERM` / `SIGHUP` | Le handler appelle d'abord `rescue()`, ce qui écrit aussi l'étape en vol dans `manifest.json` (avec `error="killed-by-signal"`), puis restaure l'action par défaut et part vraiment | Idem, ça reprend |
| `SIGKILL`, coupure de courant, redémarrage machine | Aucune clôture du tout | Ça reprend quand même — les trois fichiers sont sur disque, et le lignage est écrit à l'instant où l'id arrive |

Une seule condition : **même `workspace` et même `run_dir`**. `run_dir` est relatif au répertoire de travail courant,
donc lancer `flower` depuis un autre répertoire ira chercher un autre `runs/` et ne reprendra rien.

### Le juge est toujours une session neuve {#判定者永远是新会话}

Ce point est **garanti par construction**, pas par mémoire.

Le juge n'est pas un `Step` — il est envoyé directement par `rt.run()` depuis le gate de `with_goal`
(voir [Garde-objectif](goal.md)), et ne passe jamais par le lignage. Chaque tour, chaque réveil, c'est donc une paire d'yeux entièrement neuve.

C'est précisément là toute sa valeur : **il ignore combien de fois l'exécutant a essayé et à quel point c'était pénible, donc il ne lui cherchera pas d'excuses.**
Le faire suivre la continuité dégraderait le garde-objectif en auto-audit.

La section 4 de `tests/lineage_offline.py` verrouille ce point.

### La phrase dite au réveil doit atterrir à trois endroits {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` dans un répertoire déjà utilisé, **ce n'est pas une nouvelle tâche, c'est une phrase de plus**.
Elle fait trois choses en même temps — s'il en manque une, l'échec est silencieux :

| Où elle atterrit | Ce qui arrive si elle manque |
|---|---|
| Ajoutée à `需求.md` (`## 唤醒时追加`) | Elle ne survit pas à la frontière d'étape. L'étape suivante est une nouvelle session, qui ne lit que les pièces gelées |
| Utilisée comme prompt de l'étape de travail | Le coordinateur ne la reçoit tout simplement pas |
| **Déclenche une re-dérivation de `目标.md`** | Le juge lit encore l'ancienne liste : **savoir si la nouveauté est terminée n'entre même pas dans le verdict** |

Le troisième point est le plus facile à oublier. Le juge ne lit que le `目标.md` gelé ; ce que vous ajoutez en cours de route lui est invisible — sans re-dérivation, il jugera « atteint » selon l'ancienne liste, alors que la chose que vous vouliez n'a jamais été vérifiée. Le prix, c'est une exécution supplémentaire de la définition d'objectif à chaque ajout ([HT002](../cases/ht002.md), mesuré à
$0.41 / 3 minutes).

**Un réveil sans rien dire** (entrée directe) n'ajoute rien, ne re-dérive rien, et ne coûte pas un centime de plus.

### Un plantage à l'intérieur de la première étape (clarification) se reprend aussi {#崩在第一步确认需求之内也能接上}

`clarify_step` porte un `resume_prompt` (constante `CLARIFY_RESUME`) : après un plantage en pleine clarification, au redémarrage
on dit au [clarificateur](../reference/glossary.md#确认者) « reprends la clarification de besoin inachevée —
ce n'est pas un nouveau départ », au lieu de renvoyer la demande initiale comme une nouvelle tâche. Combiné à « écrire le session_id dès réception » ci-dessus,
une mort dans la première étape, avant que `需求.md` ne soit gelé, se reprend désormais aussi, sans avoir à tout re-répondre.

Inversement, les étapes préalables déjà gelées sont **entièrement sautées** : si `需求.md` a ses quatre sections, la clarification est sautée (mais le contenu est quand même injecté dans ctx) ;
si `目标.md` est complet, la définition d'objectif est sautée.

### À la reprise, ce n'est pas la même phrase qui est envoyée {#接续时发的不是同一句话}

C'est le rôle de `Step.resume_prompt`. L'interlocuteur **a déjà** dans son contexte le brief, l'objectif, et où il en était ; lui renvoyer
tel quel « fais selon ce besoin : <brief intégral> » est du bruit pur, et pire, cela se lit comme « le besoin a changé, relis tout ».

Sans `resume_prompt`, on retombe sur `prompt` — certaines étapes doivent justement tout renvoyer (quand la définition d'objectif re-dérive la liste,
c'est exactement le brief intégral qu'il lui faut).

### Au réveil, annoncer une ligne d'abord {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sans cette annonce, « est-ce qu'il se souvient ou pas » est totalement imperceptible — et c'est là toute la valeur de cette couche. Dans le bandeau,
`需求已确认` est toujours présent, `目标 N 条` n'apparaît que si la liste de vérification n'est pas vide, et `干活上下文 X` suppose de pouvoir retrouver dans `sessions.db`
la taille de contexte du dernier tour de cette session.

**Le chiffre de contexte est affiché délibérément** — la raison est dans la section « Le prix » plus bas.

### Résilience : attendre en suspens quand le réseau tombe, et garder les erreurs hors du contexte repris {#韧性断网时挂着等而且错误不进接续后的上下文}

La [résilience](../reference/glossary.md#韧性) va de pair avec la continuité : sur une exécution de plusieurs heures, le réseau tombera forcément une fois, et le comportement par défaut est mauvais —
à l'instant de la coupure, le harness insère dans le transcript un **message assistant synthétique** (`isApiErrorMessage=true`,
`model="<synthetic>"`), dont le corps est « API Error: Can't reach the API server … ». Ce message devient la feuille de la session,
et à la reprise il est réinjecté comme « la dernière chose que le modèle a dite » ; le modèle croit alors qu'il est en train de discuter d'une panne réseau.

`Resilience` fait trois choses :

**Un. La sonde se limite à DNS + TCP.** `reachable(host, port, timeout=5.0)` ne fait qu'un `getaddrinfo` et une poignée de main TCP,
**pas de HTTP, pas d'identifiants, pas de coût** ; toute exception compte comme injoignable. L'adresse sondée est décidée par `endpoint()`, qui suit
`ANTHROPIC_BASE_URL`, avec `https://api.anthropic.com` par défaut et le port `443` par défaut (`80` en http).
**Avec une passerelle auto-hébergée, il faut sonder la passerelle** — `api.anthropic.com` joignable ne prouve rien sur la passerelle.

**Deux. Distinguer ce qu'il faut attendre de ce qu'il faut arrêter.** `classify(text)` renvoie `"transient"` / `"fatal"` / `"unknown"`,
et **teste fatal avant transient** — les textes de type 401 contiennent souvent le mot « connection » ; dans l'ordre inverse, on attend indéfiniment.
Valeurs par défaut : `max_attempts=6` (première tentative incluse), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 heure), `retry_unknown=True`.
Le backoff est `min(base_delay * 2**(attempt-1), max_delay)` multiplié par une gigue de ±25%.

Si un session_id a déjà été obtenu, on **reprend la session au lieu de tout refaire** ; les dépenses antérieures ne sont pas perdues. À la reprise, on envoie
`Resilience.resume_prompt` : « le tour précédent a été interrompu en cours de route, il n'est pas allé au bout. Regarde ce qui est déjà écrit dans l'établi,
reprends au point d'interruption, ne recommence pas depuis le début. » Il **ne contient volontairement aucun détail d'erreur** — le modèle doit savoir « tu as été interrompu, continue »,
pas s'il s'agissait d'un ENOTFOUND ou d'un 503.

**Trois. Les erreurs produites par la tempête de retries n'entrent pas dans le contexte après reprise.** C'est le travail de l'[élagage](../reference/glossary.md#剪除).
Le stockage de sessions de `Runtime` est câblé sur `PruningSessionStore`, qui fait trois choses au `load()` :

- Retirer les messages d'erreur API synthétiques. **Ils restent intacts dans SQLite**, ils ne sont simplement pas réinjectés
- Retirer les appels refusés trop anciens, n'en garder que les `keep_denials=1` plus récents
- Remplacer les `tool_result` résiduels d'une interruption par une note neutre « [上一轮在此处被中断,该工具结果未产生] », en ne changeant que le corps, sans retirer l'entrée

Garder 1 entrée plutôt que 0 a une raison : un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information, mais il occupe une place non négligeable
(mesuré une fois à 273 caractères = 93 caractères de refus + 180 caractères de **commande bloquée en clair**), et **il induit en erreur** —
en pratique, après avoir lu quelques « ne pas utiliser Bash directement », le coordinateur n'essayait même plus un `git status` pourtant autorisé : impuissance apprise.
Mais garder la plus récente est utile : cela évite que le modèle retente en boucle la même commande bloquée dans le même tour.

Le retrait a une ligne rouge structurelle : le transcript est une chaîne simple par `parentUuid` ; retirer une entrée oblige à rattacher ses enfants à l'ancêtre vivant le plus proche,
sinon la chaîne casse là et tout l'historique antérieur est perdu.

[HT001](../cases/ht001.md) a rencontré le cas une fois : coupure réseau de 01:52:40 → 01:55:41, l'étape correspondante dans `manifest.json` est
`attempts=2` / `resumed=True` / `ok=True`, et après reprise elle a encore tourné plus de 8 heures jusqu'à complétion.

Un dernier point souvent mal compris : **`Runtime(trim=False)` ne veut pas dire « on ne nettoie rien »**. `trim` vaut `False` par défaut,
mais il ne désactive que la couche de **[rognage](../reference/glossary.md#裁剪) des gros résultats d'outils**. Retirer les résidus de coupure, retirer les appels refusés,
neutraliser les résidus d'interruption, marquer périmés les résultats de [commandes éphémères](../reference/glossary.md#一次性命令) — ces quatre-là ont toujours lieu
(`ephemeral` vaut `True` par défaut, `keep_denials` vaut `1` par défaut).

### Le prix : le contexte grossit sans fin {#代价上下文会一直涨而且没有尽头}

C'est le coût intrinsèque de la continuité, pas un bug.

L'étape « travail » de [HT001](../cases/ht001.md) a tourné 10.44 heures d'affilée ; le contexte du [fil principal](../reference/glossary.md#主线程) était de
**28.7K** au tour 1, **35.2K** au tour 20, **108.6K** au tour 35, **158.2K** au tour 50, **185.9K** au tour 70,
croissance monotone, pente d'environ **2.2K/tour** ; jamais compacté, soit **18.6%** de la fenêtre de 1M utilisés. En extrapolant à cette pente,
le mur est vers **440 tours** — la limite du « long horizon » sous sa forme actuelle vaut environ **6 fois** cette exécution. Une continuité permanente signifie qu'un jour on tapera la fenêtre.

Deux mécanismes s'en occupent :

1. **Rognage** (désactivable avec `flower --no-trim`, actif par défaut sur le chemin `flower`) — à la reprise, les gros résultats d'outils anciens sont remplacés par
   des pointeurs de fichiers ; le contenu n'est pas perdu, il ne réside simplement plus en permanence
2. **[Passation](handoff.md)** — au seuil, on écrit un document de passation et on change de session. **Ce n'est pas du [compact](../reference/glossary.md#压缩)** :
   le document est lisible et modifiable, vous voyez ce qui a été perdu. Le contexte redescend donc périodiquement au lieu de monter jusqu'au mur

**D'où la nécessité d'afficher le chiffre de contexte au réveil** : si l'humain le voit, il a une chance de décider lui-même de repartir à zéro avant le mur.

En passant : `--rounds` (nombre total de tours de travail) **est remis à zéro à chaque réveil**. C'est volontaire — un nouveau réveil est une nouvelle intention,
il ne doit pas hériter des tours consommés la fois précédente.

### Repartir sur autre chose {#重开一件事}

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

**Archiver, pas supprimer.** `lineage.json`, `需求.md`, `目标.md` sont **déplacés ensemble** dans `notes/archive/<YYYYmmdd-HHMMSS>/`,
et `steps` et `woke` du lignage sont remis à zéro en même temps. Ces trois éléments sont trois faces d'un même historique ; n'en ranger qu'une partie laisserait un état bâtard du genre « l'objectif est encore là mais la conversation a disparu ».

`sessions.db` n'est pas touché — c'est l'archive, chaque transcript y reste consultable.

Côté code, cela correspond à `Lineage.archive(into, extra=[...])`.

## Quand ne pas l'utiliser {#什么时候不该用它}

- **Les cas qui exigent un point de départ propre à chaque fois.** Exécuter le même workflow en lot, faire une évaluation comparative, reproduire un bug pour quelqu'un —
  rien de tout cela ne doit traîner le contexte précédent. Écrivez `Workflow(..., continuous=False)`, ou changez de `run_dir` à chaque fois.
- **Le répertoire va être déplacé ou copié, ou `run_dir` n'est pas persistant.** Exécution en conteneur avec `runs/` sur le système de fichiers interne du conteneur,
  ou espace de travail rsyncé vers une autre machine — la continuité **échoue silencieusement** (la garde de chemin rejette un lignage qui ne correspond pas),
  ne la prenez pas pour une garantie.
- **C'est une nouvelle intention et le contexte est déjà gros.** La continuité vous fera porter un historique sans rapport, et vous paierez des tokens pour lui à chaque tour.
  Plutôt que de subir, archivez et repartez avec `--new`.
- **Agent unique ponctuel.** `flower once` ne passe pas par `Workflow`, il n'y a pas de lignage ; pour reprendre, il faut fournir soi-même `--resume <session_id>`.
- **Prendre la continuité pour une sauvegarde.** Elle ne retient que « quelle étape a utilisé quelle session ». Le code, les livrables et les décisions doivent atterrir dans l'espace de travail et dans l'[établi](../reference/glossary.md#工作台), pas être déterrés d'un transcript.

## À lire ensuite {#相关}

- [Passation](handoff.md) — que faire quand le contexte sature à l'intérieur d'une même exécution ; c'est l'autre direction de la même chose
- [Garde-objectif](goal.md) — pourquoi le juge ne reprend jamais
- [Économie du contexte](context.md) — ce dont s'occupent respectivement le rognage, l'élagage et le spill
- [API Python](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Ligne de commande](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Sources : [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
