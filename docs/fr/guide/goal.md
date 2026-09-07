# Gardien d'objectif

« C'est fini ou pas » n'est pas à l'exécutant de le dire. Le [juge](../reference/glossary.md#判定者) est un rôle qui
fixe uniquement l'objectif, juge uniquement, et ne met jamais la main à la pâte : avant le départ, il transforme le
[brief](../reference/glossary.md#需求确认书) en une checklist jugeable, puis, à la fin de chaque round de travail,
il **juge une fois, indépendamment**, et produit un [verdict](../reference/glossary.md#判定) —
atteint, on continue ; pas atteint, on renvoie le travail avec « ce qui manque » ;
jugé impossible, on s'arrête et on demande à l'humain.

## Quel problème cela résout

La [clarification préalable](clarify.md) bloque **« ce n'est pas la chose voulue qui est faite »**. Cette couche-ci
bloque une autre catégorie : **« ce n'est en fait pas fini, mais il dit lui-même que c'est fini »**. Les deux doivent
rester séparées, car les modes de défaillance diffèrent :

| | À quoi ressemble l'échec | Quand il se révèle |
|---|---|---|
| Besoin erroné | Chaque livrable est construit sur un besoin faux | Des heures plus tard, tout le produit est bon à jeter |
| Jugement d'achèvement erroné | Tests à moitié exécutés, un endroit corrigé et trois oubliés, « ça devrait aller » | Quand vous l'utilisez vous-même |

Pourquoi la deuxième catégorie ne peut pas être confiée à l'exécutant lui-même : **il a un biais d'optimisme
systématique**. Ce n'est pas de la malhonnêteté — il ne voit pas son propre angle mort. Il sait ce qu'il a fait,
il ne sait pas ce qu'il a oublié.

Le jugement est donc confié à un rôle qui **n'a pas participé au travail et tourne dans sa propre
[session](../reference/glossary.md#会话)**. Il ne voit que l'objectif et le terrain, il ignore combien de fois
l'exécutant a essayé et à quel point ça a été dur — il ne lui trouvera donc pas d'excuses.
C'est exactement la même raison qui fait tourner le clarificateur dans une session indépendante.

## Comment s'en servir (code minimal)

### Zéro code : ligne de commande

```bash
flower                      # le gardien d'objectif est actif par défaut
flower --no-goal            # désactivé : le travail terminé vaut achèvement
flower --rounds 5           # cinq rounds de travail au maximum (défaut : 3)
flower --judge-can-run      # laisse le juge exécuter des commandes (jugement plus dur)
```

### Câblage manuel

Deux fonctions, chacune sa moitié, à ne pas mélanger : `goal_step()` **fixe l'objectif** (une étape à part entière),
`with_goal()` est la **boucle de jugement** (elle emballe une étape de travail).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # aucune limite de questions par défaut
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)` :

| Paramètre | Défaut | Description |
|---|---|---|
| `goal_path` | — | Où atterrit l'objectif. Sous `notes/` du [plan de travail](../reference/glossary.md#工作台), même raison que pour le brief |
| `brief_key` | `"确认需求"` | Depuis quelle clé de `ctx` lire le brief. **S'il est introuvable, on n'obtient que `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nom de l'étape, et aussi nom de la clé dans `ctx` |
| `spec` / `instructions` | `None` / `""` | Fournir son propre `AgentSpec`, ou ajouter des instructions métier au juge |
| `always_set` | `False` | `True` = redéfinir à chaque fois |
| `on_fail` / `retries` | `"stop"` / `0` | Comme pour `Step` |
| `**spec_kw` | — | Transmis à `judge()` : `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` emballe une étape de travail dans une boucle avec jugement :

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` est le nombre total de rounds, pas le nombre de rounds supplémentaires** — il se traduit par
`retries = max(0, rounds - 1)`, donc `rounds=3` fait au maximum trois rounds de travail, et `rounds=1` signifie
« un round, un jugement, échec si le jugement ne passe pas ».
Signature complète et sémantique des champs dans [Python API](../reference/api.md).

Trois clés supplémentaires apparaissent dans `ctx` :

```python
ctx[GOAL_KEY]     # "_goal" —— objet Goal ; ctx["设定目标"] en est le markdown
ctx[VERDICT_KEY]  # "_verdict" —— dernier Verdict en date, pour l'UI
ctx[ROUND_KEY]    # "_goal_rounds" —— nombre de rounds effectués
```

Le juge est lancé via `ctx["_runtime"]` — `Workflow.run` place le runtime et la sortie d'événements dans `ctx`,
si bien que le `gate` peut démarrer son propre agent, et que le processus de jugement s'affiche quand même dans
votre UI (sinon l'interface reste noire une dizaine de secondes et donne l'impression d'un blocage).

Quand ça ne tourne pas rond, commencez par ces boutons :

| Symptôme | Quel bouton tourner |
|---|---|
| Jugement trop laxiste, dit atteint alors que ça ne l'est pas | `--judge-can-run` pour qu'il exécute vraiment ; ou ajouter des critères métier dans `instructions` |
| Jugement trop strict, renvoie sans arrêt | Regardez si la checklist de jugement de `目标.md` place la barre plus haut que le besoin. **Modifiez ce fichier** |
| Ça tourne à vide round après round | Le juge aurait dû rendre « impossible » et a rendu « pas atteint ». Ajoutez-lui des instructions expliquant ce qui compte comme infaisable |
| Trop cher | `--rounds 1`, ou `--no-goal` pour tout désactiver |
| Ne pas être interrompu | `--timeout 0` : en cas d'impossibilité, on ne demande pas, on s'arrête directement (la raison reste sur le disque) |

## Ce qu'il fait réellement

### À quoi ressemble un objectif

`goal_step` lit le brief, produit deux sections, et les gèle dans `.flower/notes/目标.md` :

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**La checklist de jugement est toute la valeur de cette couche.** « Implémentation complète » n'est pas jugeable ;
« quoi exécuter, quoi observer » l'est. La checklist vient des « critères d'acceptation » du brief, mais doit être
réécrite de sorte que chaque ligne soit vérifiable sur-le-champ — les lignes vagues, le juge les complète.
Les deux sections doivent être non vides (`statement` dit quelque chose, `checks` n'est pas vide) pour que ce soit
complet ; sinon l'étape ne laisse pas passer.

### La longueur de la checklist est dictée par « combien de modes de défaillance existent »

Pas par la rigueur du juge. Pour une tâche du type `git clone && make && ./app`, **trois à cinq lignes suffisent** :
la compilation passe, ça démarre, c'est utilisable.

**Vécu en conditions réelles** ([HT002](../cases/ht002.md)) : une tâche « installer le dépôt et le faire tourner »
a donné une checklist de **15 lignes**, dont seulement **5** vérifiaient « est-ce que la chose marche »,
**6** vérifiaient « est-ce que le processus a respecté les règles »
(dont vérifier le mtime de `~/.zshrc`, vérifier si le répertoire `.flower/` avait été modifié — c'est le répertoire
du framework lui-même), et **4** étaient invérifiables par principe.

#### Une limite n'est pas un critère de jugement

C'est la cause principale de cet épisode :

| | Contraint quoi | Comment on s'y conforme |
|---|---|---|
| **Limite** | **Comment vous travaillez** (« n'installer que dans le répertoire du projet », « ne pas toucher au code métier ») | En **ne franchissant pas la limite**, pas en se justifiant après coup |
| **Critère de jugement** | **Ce qui est livré** (« ça tourne ou pas », « le résultat est correct ou pas ») | Par vérification sur-le-champ |

Écrire « n'a pas exécuté `brew install` » comme critère de jugement revient à ajouter une vérification à chaque limite
ajoutée — et les limites sont précisément ce que la phase de clarification encourage à écrire en abondance.
S'il faut vraiment rendre des comptes, une phrase suffit ; ne la découpez pas en six lignes.

### Les items invérifiables sont signalés dès la définition de l'objectif

Pour les items marqués `[此环境无法验证:原因]` dans la checklist, `goal_step` émet un avertissement
**au moment même où il gèle l'objectif** :

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Pourquoi si tôt** : le sort de ces items est scellé dès l'instant où l'objectif est fixé, ils ne passeront jamais
au jugement. Dans HT002, on avait d'abord dépensé **$35.90 de travail + $1.40 de jugement** avant de le découvrir —
en avançant la découverte à l'étape de définition de l'objectif, la même information passe de **$37** à **$0**.

Simple avertissement, pas de blocage : l'humain peut choisir de tourner quand même (à la fin de HT002, il a choisi
« accepter ce résultat »). `Goal.unverifiable` contient cette liste, et le payload de l'événement fournit les données
structurées pour l'UI.

### Trois conclusions, pas deux

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

La troisième conclusion est déterminante. Avec seulement « atteint / pas atteint », un objectif **en réalité
infaisable** ferait tourner le coordinateur à vide, round après round, jusqu'à épuisement du budget — et c'est là que
l'argent brûle vraiment. Le juge a donc pour consigne explicite : n'est « impossible » que ce dont
« un round de plus ne changerait rien » (condition externe nécessaire absente, besoin contradictoire, critère de
jugement fondamentalement invérifiable) ; « pas encore fini » relève de « pas atteint ».

En cas d'impossibilité, le framework s'arrête et demande à l'humain :

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Accepter** → l'étape est considérée comme passée, la raison reste consignée
- **Modifier l'objectif** → on vous demande ensuite le nouvel objectif, qui est **ajouté à la suite** de l'ancien
  (on voit ce qui a changé), puis un nouveau round
- **Tu t'es trompé** (ainsi que toute réponse libre que vous tapez) → le travail est renvoyé avec votre argument,
  puis un nouveau round

**Sans réponse humaine, ça s'arrête**, ça ne continue pas à tourner à vide — c'est délibéré. Jugé infaisable et
personne à qui demander : continuer, c'est brûler de l'argent round après round, et c'est précisément ce qu'il faut
éviter. À l'arrêt, un `StepAbort` est levé, la raison est écrite dans `ctx["_aborted"]`, le fichier d'objectif et
`runs/manifest.json` sont là, l'humain revient et décide.

!!! warning "« pas fait » et « invérifiable ici » sont deux conclusions distinctes"
    Les trois valeurs de `Verdict` sont `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` ne doit jamais être traité comme un succès** — il emprunte le chemin « s'arrêter et demander »,
    pas celui de « un round de plus ». Tout ce que le juge écrit comme
    « invérifiable / impossible à vérifier / ne peut pas être vérifié / indécidable / unverifiable » est **entièrement**
    rangé sous `UNREACHABLE`. Traiter « invérifiable ici » comme « atteint », c'est clore le travail sur un
    « ça a l'air de marcher » ; le traiter comme « pas atteint », c'est le faire recommencer round après round une
    chose de toute façon invérifiable.

### Jugement vague = pas atteint

Ordre de reconnaissance de `Verdict.parse` : d'abord la section titrée « 结论 / 判定 » ; en l'absence de section titrée,
un texte entier valant `1` / `true` compte pour atteint, `0` / `false` pour pas atteint (quand on demande au juge de
« ne renvoyer que 0/1 », il ne renvoie très probablement qu'un chiffre) ; sinon on cherche des mots-clés dans le texte
de conclusion (mots longs en premier) ; en dernier recours, un `1` / `0` isolé.

**Si rien ne correspond, `state` reste vide, `ok` vaut `False`, et le framework traite le cas comme « pas atteint ».**
C'est délibéré : « impossible de trancher » et « c'est fini » sont deux choses différentes ; le flou est
systématiquement traité comme « pas atteint », avec une raison par défaut ajoutée
(« le juge n'a pas rendu de conclusion claire, traité comme pas atteint »).

### Ce qui est jugé, c'est le livrable, pas le code source

!!! warning "Un jugement qui ne lit que le code source ne peut pas juger le livrable"
    Dans [HT001](../cases/ht001.md), le critère d'acceptation disait littéralement « produire un exécutable autonome,
    qui tourne directement dans un terminal macOS », et le jugement s'est contenté de lire `Makefile:25-38`,
    d'y trouver une branche Darwin, et de conclure **succès** — le livrable était en réalité un
    `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Ce n'est pas le gardien d'objectif qui s'est trompé** : ce run n'avait pas encore ce mécanisme, et c'est un
    auditeur indépendant improvisé par le coordinateur lui-même qui a jugé cette ligne. Mais le gardien d'objectif
    serait passé à côté de la même façon — le juge a `can_run=False` par défaut, il n'a que
    `Read` / `Glob` / `Grep`, il **ne peut pas exécuter `file`**, il n'aurait donc pu que lire le `Makefile` et
    conclure « atteint » en voyant la branche Darwin. Le nœud de cet échec n'est pas « qui juge », mais
    « sur quelles preuves on juge ».

    Cette leçon est inscrite dans `JUDGE_RULES` : ce qui est jugé, c'est le **livrable** ; on n'accepte pas les
    déductions du type « il y a une branche macOS dans le source, donc ça devrait tourner ».

[HT002](../cases/ht002.md) est le run où `judge_can_run` était activé et où le juge a réellement exécuté
`file` / `lsof` ; il a donc évité ce piège — sa première phrase a été « je ne conclus pas à partir de ce discours.
Je vais sur le terrain. » Puis :

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

La phrase du prompt de jugement dit la même chose : va voir sur le terrain toi-même, reprends la checklist ligne par
ligne, et **un critère de jugement dont tu ne vois pas la preuve est un critère non passé**.

### « Renvoyer » signifie continuer, pas recommencer

Le renvoi utilise `Step.on_reject` : au round suivant, on **`resume` la session qui vient d'être recalée**, avec un
prompt remplacé par le retour du jugement (`Verdict.feedback()` ne donne que « ce qui manque », pas la solution).
Le travail déjà fait, les fichiers déjà lus, les détours déjà pris restent donc dans le contexte ; il n'a plus qu'à
combler l'écart.

La différence apparaît dans le nom de l'étape, visible d'un coup d'œil dans `runs/manifest.json` :

```text
干活            第一轮
干活#round2     被打回后接着做      ← on_reject 生效,resume 上一轮
干活#retry1     普通重试(重头跑)    ← 没有 on_reject 时的老行为
```

Le juge, lui, est **toujours dans une nouvelle session** : le `gate` de `with_goal` appelle directement `Runtime.run`,
sans `resume` ; le nom de l'étape porte le numéro de round (`干活·判定#1`), et les noms suffixés n'entrent pas dans la
[lignée](../reference/glossary.md#血缘) inter-processus.
Si le `gate` n'obtient pas `ctx["_runtime"]`, il lève `StepAbort` — **il ne fait pas semblant de passer**.

### Saut et redéfinition

Si le fichier d'objectif existe déjà et est complet, l'étape est **sautée** (comme pour le brief) — quand un run
[long-horizon](../reference/glossary.md#长程) plante et redémarre, il ne faut pas recalculer les conclusions déjà
établies. Pour redéfinir, supprimez ce fichier, ou passez `always_set=True`.

**Exception : au réveil, vous avez ajouté une phrase.** Cette phrase est ajoutée au brief, et l'étape **redérive**
donc l'objectif (`always_set=True`). Sans redérivation, le juge lirait encore l'ancienne checklist gelée, et la chose
que vous venez d'ajouter n'entrerait tout simplement pas dans le jugement — il conclurait « atteint » selon
l'ancienne checklist. Coût mesuré de la redérivation : **$0.41 / 3 minutes**.
Voir [continuité](continuity.md).

### Le juge peut-il exécuter des commandes

Par défaut **non**. La liste de pré-approbation de `judge()` contient les outils de question plus
`Read` / `Glob` / `Grep` ; `Bash` ne s'ajoute qu'avec `can_run=True`. L'arbitrage :

- Donner `Bash` (`--judge-can-run` en CLI) → il peut réellement exécuter les commandes d'acceptation, le jugement est plus dur
- Mais il peut alors modifier l'espace de travail → il pourrait « corriger vite fait » avant de conclure au succès,
  et ce jugement n'aurait plus aucun sens

Comme pour le clarificateur, **pas de `Write` / `Edit` / `Agent`**. Ce qui applique cette règle, c'est le hook
`whitelist_guard`, **pas `allowed_tools`** — ce dernier est une **liste de pré-approbation, pas une liste blanche
exclusive**, le modèle peut parfaitement appeler des outils qui n'y figurent pas. Les preuves mesurées qui tiennent
toujours : dans HT002, le juge de l'étape « 设定目标 » a exécuté **11 fois `Bash`** alors que sa liste de
pré-approbation ne contenait pas du tout `Bash` ; et dans la **sonde à $0.1**, un agent avec
`allowed_tools=["Read"]` a quand même émis des appels `Write` et `Bash`, bloqués par la couche de permissions et la
sécurité des chemins
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Aujourd'hui ces deux appels sont `deny` sur-le-champ par le hook —
**ce qui l'arrête, c'est le hook, pas la liste**.

!!! warning "Le juge qui fixe l'objectif n'a pas `Bash` par défaut"
    `goal_step()` **n'a pas de paramètre `can_run`** ; il faut passer par `**spec_kw` : `goal_step(ch, goal_path=…, can_run=True)`.
    Sans le préciser, il n'a pas `Bash`, et la règle de `JUDGE_RULES` « commence par `uname -a` pour savoir où tu es »
    ne peut pas s'appliquer — il risque donc de vous écrire une checklist tout simplement invérifiable sur cette
    machine. `with_goal()` est un autre cas : il a son propre paramètre `can_run` (défaut `False`).

### Pourquoi le nombre de rounds est plafonné, mais pas le nombre de questions

Poser une question ne coûte presque rien, un round de travail coûte de l'argent réel. Donc :

- **Questions illimitées** (`max_asks=None`) — jusqu'à ce que ce soit clair, le clarificateur en juge lui-même
- **Rounds plafonnés** (`rounds=3`) — mais le vrai garde-fou n'est pas ce chiffre, c'est la troisième conclusion
  « impossible » : dès qu'elle apparaît, on s'arrête et on demande, sans attendre l'épuisement des rounds

## Quand il ne faut pas l'utiliser

**Quand la tâche est si petite que juger est plus verbeux que faire.** Cette couche complique les problèmes simples,
et c'est mesuré : pour ce « cloner un dépôt, l'installer et le faire tourner sur macOS » de HT002, la checklist de
jugement a été écrite en 15 lignes, dont 6 vérifiaient le respect du processus et 4 étaient invérifiables par
principe ; ce round de jugement a coûté à lui seul **$1.4037 / 37 tours / 0.09h**, pour un run total de
**$38.2409 / 0.97h**. Quand une tâche n'a de toute façon que deux ou trois modes de défaillance, `--no-goal` est plus
rentable.

**Quand l'objectif ne se laisse pas écrire en checklist jugeable.** Un travail exploratoire (« regarde un peu de quoi
parle ce dépôt ») n'a pas de critère de « fini » ; forcer un objectif ne produira qu'une belle checklist injugeable.
Pour ce genre de travail, utilisez `flower once`, ou `--no-goal`.

**Quand le critère de jugement décisif est invérifiable dans cet environnement.** Le juge a `can_run=False` par
défaut, avec pour seuls outils `Read` / `Glob` / `Grep` — **il ne peut pas exécuter `file`**, il ne peut que lire le
source. Le critère « tourne directement dans un terminal macOS » de [HT001](../cases/ht001.md) : tout le run se
déroulait dans un conteneur Linux — **aucun juge, quel qu'il soit, ne peut vérifier un binaire macOS depuis le
conteneur**, qu'il s'auto-évalue ou qu'il soit indépendant. `--judge-can-run` en sauve une partie (au moins `file`
devient exécutable) ; la partie qu'il ne sauve pas doit être marquée `[此环境无法验证:…]` dès la définition de
l'objectif, pour emprunter le chemin « s'arrêter et demander », plutôt que d'espérer que le juge devienne plus malin.

**En mode sans surveillance et sans interruption possible.** Si le verdict est « impossible » et que personne ne
répond, l'étape **s'arrête**, et tout le [workflow](../reference/glossary.md#流程) s'arrête là. Si vous voulez
« que ça aille jusqu'au bout d'abord », prenez `--no-goal` ; si vous voulez « que ça s'arrête mais sans attendre »,
prenez `--timeout 0` — la question échoue immédiatement et la raison est écrite sur le disque.

**Il ne juge pas si le besoin est correct.** La checklist de jugement est dérivée du brief ; si le brief est faux,
le jugement ne fera que vérifier précisément une chose fausse. Cela relève de la couche
[clarification préalable](clarify.md).
