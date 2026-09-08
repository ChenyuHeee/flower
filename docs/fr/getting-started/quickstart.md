# Démarrage rapide

Trois commandes suffisent pour le faire tourner : installer, entrer dans le répertoire du projet, taper `flower`. Cette page met ces trois commandes tout en haut,
puis explique ce qui se passe à l'écran après avoir appuyé sur Entrée, comment répondre quand il vous pose une question, et par quoi commencer quand ça ne démarre pas.

## Installer, entrer dans le répertoire, taper flower {#跑起来}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
cd /path/to/your/project
flower
```

Le premier script cherche automatiquement `uv` / `pipx` / `pip` pour installer la commande `flower` ; il suffit d'avoir Python ≥ 3.10,
sans installer Node ni le CLI Claude Code. La troisième ne prend aucun argument et **n'exige aucune paire de guillemets dans le shell**.

Pour une autre méthode d'installation (pipx / pip / depuis les sources), ou si ce script ne fonctionne pas sur votre machine, voir [Installation](install.md) —
mais inutile de lire cette page en entier avant de revenir ici.

## Après avoir appuyé sur Entrée {#回车之后}

Au premier run sur cette machine, il demande d'abord les identifiants : clé API ou adresse de passerelle. Une seule configuration, stockée dans
`~/.config/flower/.env`, vaut partout ensuite. Si Claude Code est déjà installé et configuré sur la machine,
il emprunte directement ce token, sans même poser la question.

Une fois les identifiants en place, le curseur s'arrête sur `>` :

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Cette ligne lit l'entrée standard, **sans passer par l'analyse du shell** — guillemets chinois, espaces, points d'exclamation se tapent directement.

Avant de démarrer, il affiche une ligne `- 验一下凭证…` : c'est une vraie sonde API. Si les identifiants sont refusés, il affiche `! 凭证被拒:…`
et vous demande sur-le-champ si vous voulez reconfigurer ; s'il n'arrive pas à se connecter, il affiche `(探针没打通:… —— 当作网络问题,照常开跑)`,
et il ne vous fait **pas** reconfigurer un token qui marchait très bien.

Une fois la sonde passée, il se met au travail, en trois étapes. Chaque ligne de tirets `==` à l'écran marque une frontière
d'[étape](../reference/glossary.md#步骤), et le `1/3` à droite est la progression :

```text
== 确认需求 ======================================================== 1/3

  ? X 要跑在什么环境上?
     1) 只在我这台 macOS 上
     2) Linux 服务器
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
  + 只在我这台 macOS 上

  ? 「做完了」以什么为准?
你的回答 (回车=跳过,让它自己判断) > 能跑起来,并且 pytest 全绿
  + 能跑起来,并且 pytest 全绿

  + 完成 9 轮 · $0.53 · 用时 6:02

== 设定目标 ======================================================== 2/3

  ~ 把这份需求拆成能当场验证的条目
  + 完成 12 轮 · $0.41 · 用时 9:06

== 干活 ============================================================ 3/3

  ~ 先看一眼现在有什么,再决定第一刀切哪
  * Read README.md
  > 派人 coder 实现 X 的第一版,带最小测试
  先让 coder 把骨架搭起来,我再看要不要拆第二个人。
  - 上下文 36.8K · 累计 $0.94 · 12:44
  + 完成 12 轮 · $12.34 · 用时 52:53
  + 完成 37 轮 · $1.40 · 用时 58:19

总花费 $14.68 · 清单 /path/to/your/project/runs/manifest.json
```

Les icônes sont toutes en ASCII : `~` réflexion, `*` appel d'outil, `>` délégation, `+` succès, `x` échec, `?` question, `<-` reprise.
Pas d'emoji — emoji et caractères de cadre déclenchent des replis de glyphes dans le terminal ; deux terminaux ont réellement planté à l'essai. **Tous les exemples
de terminal de cette documentation utilisent ce jeu ASCII, identique à ce que vous avez à l'écran.**

Trois autres points méritent un second regard :

- Les deux dernières lignes `+ 完成` ne sont pas un doublon. La première est le tour de travail, la seconde est le tour de **verdict** —
  le verdict tourne dans sa propre session, mais **n'ouvre pas de nouvelle ligne `==`**, parce que c'est un tour interne à l'étape `干活`.
  Dans le [run manifest](../reference/glossary.md#运行清单), il s'appelle `干活·判定#1`.
- Le `$` de la ligne `+ 完成` est le coût de **ce tour-là**, tandis que `用时` est la durée totale **depuis le démarrage jusqu'à maintenant** : deux mesures différentes.
- Les lignes d'état du type `- 上下文 … · 累计 … · …` ne suivent que le [thread principal](../reference/glossary.md#主线程) ;
  le contexte des subagents n'y figure pas. Les appels d'outils des subagents s'affichent par défaut, indentés derrière une barre `|` ;
  **ce qu'ils disent** n'apparaît qu'avec `-v` — c'est du terrain, pas de la décision.

## Qui fait tourner chacune de ces trois étapes {#三步}

| Étape à l'écran | Qui la fait tourner | Ce qu'elle fait | Figée en | Détails |
|---|---|---|---|---|
| `确认需求` | [clarificateur](../reference/glossary.md#确认者) | Ne fait que poser des questions, ne touche à rien, **jusqu'à ce que ce soit clair, sans limite de tours** ; produit à la fin un [brief](../reference/glossary.md#需求确认书) en quatre sections | `.flower/notes/需求.md` | [Clarification préalable](../guide/clarify.md) |
| `设定目标` | [juge](../reference/glossary.md#判定者) | Traduit le brief en « objectif + liste de verdicts », chaque entrée devant être vérifiable sur-le-champ | `.flower/notes/目标.md` | [Gardien d'objectif](../guide/goal.md) |
| `干活` | le [coordinateur](../reference/glossary.md#协调者) délègue à des [subagents](../reference/glossary.md#subagent) | Le coordinateur découpe le travail et délègue, lit les rapports, décide ; à la fin de chaque tour, un juge **qui n'a pas participé au travail** décide indépendamment si « c'est fini », et renvoie la copie tant que l'objectif n'est pas atteint | le code lui-même | [Gardien d'objectif](../guide/goal.md) |

Les deux premières étapes sont la mise en œuvre des deux mécanismes [clarification préalable](../reference/glossary.md#前置确认) et [gardien d'objectif](../reference/glossary.md#目标看守) ;
la troisième est le segment qu'ils encadrent ensemble. Par défaut, au maximum 3 tours de verdict (`--rounds`),
et `--no-goal` désactive tout — une fois désactivé, « il dit que c'est fini » veut vraiment dire que c'est fini.

Le verdict n'a que trois conclusions : atteint, pas atteint, **invérifiable dans cet environnement**. Les deux dernières sont des conclusions distinctes —
« impossible à vérifier ici » ne vaut jamais un succès : il s'arrête et vous demande.

Un run complet n'est pas bon marché. Mesures réelles : [HT002](../cases/ht002.md) a installé et fait tourner un projet existant sur macOS —
4 étapes, environ 1 heure, **$38.24** ; [HT001](../cases/ht001.md) a écrit un IDE de terminal à partir de zéro —
**10.4 heures, $171.62**. Pour voir d'abord quelles questions il pose avant de décider d'aller plus loin, utilisez `--clarify-only`.

## Comment répondre aux questions {#答提问}

Le bloc qui commence par `?` est une question qu'il vous pose ; trois façons de répondre :

- **Taper un numéro** (`1` / `2` / `3`) — choisit cette entrée ; l'écran renvoie une ligne `+ <选中的那条>`.
- **Taper du texte** — réponse libre, pas nécessairement une des options.
- **Appuyer directement sur Entrée** — passe la question et le laisse juger seul ; l'écran renvoie une ligne `. 已跳过`.

Il vous attend 1800 secondes par défaut (`--timeout`). Sans personne au bout, il affiche
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」`, puis continue : il ne se bloque pas.
Le nombre de questions est **illimité par défaut** (`--asks` vaut `-1`) ; une valeur positive est un quota strict, et une fois épuisé il affiche `! 提问额度用完`.

## Vous pouvez encore parler pendant qu'il tourne {#插话}

Il y a toujours, tout en bas de l'écran, une invite où l'on peut taper. Ce n'est pas décoratif — elle est effacée avant chaque sortie et redessinée après,
donc elle **ne se fait pas repousser vers le haut par les logs**. Deux libellés, selon qu'il y a ou non une question en attente de réponse :

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Quand aucune question n'est en attente, vous pouvez faire deux choses.

**Taper une phrase = ajouter une exigence.** Il n'est pas interrompu ; il la verra à sa prochaine consultation de la boîte de réception. L'accusé de réception ressemble à ceci :

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

« 已追加进确认书 » est important : cette phrase est en même temps écrite dans `需求.md`, elle survit donc à la frontière d'étape —
l'étape suivante est une nouvelle session qui ne lit que les fichiers figés ; sans écriture sur disque, ce que vous avez dit n'existe pas.

**Commencer par `?` = poser une question au passage.** Il ouvre une session en lecture seule pour vous répondre, avec seulement les 60 derniers événements et
ce qu'il y a dans le [workbench](../reference/glossary.md#工作台). Cette voie de dérivation est tenue par
l'[oracle](../reference/glossary.md#旁路顾问), plafonnée par défaut à 12 tours / $0.5 :

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Jeté après réponse** — cet échange n'entre pas dans le contexte du run en cours, son coût n'entre pas dans le run manifest principal :
il est enregistré dans son propre fichier sous `runs/aside/`. Poser une question n'affecte donc pas le run, et vous n'avez pas à regretter la dépense imputée.

!!! warning "Le `？` pleine chasse ne compte pas, il faut un `?` demi-chasse"
    La détection des questions de dérivation ne reconnaît que le `?` **demi-chasse** (ASCII `0x3f`). Le `？` pleine chasse produit par défaut par les méthodes de saisie chinoises n'est pas reconnu —
    cette ligne est traitée comme « ajouter une exigence » et part dans la boîte de réception, **sans erreur** ; simplement, la réponse que vous attendez ne viendra jamais.
    C'est une coquille dans le code, déjà consignée dans la liste des défauts ; en attendant le correctif, basculez votre méthode de saisie en anglais avant de taper `?`.

Au passage, à propos de Ctrl+C : le premier appui en cours de run **interrompt le tour et vous laisse dire quelque chose**, il ne quitte pas.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Un second appui quitte pour de bon. (Sur l'invite initiale `要做什么?`, Ctrl-C quitte directement en affichant `已取消`.)

## Relancer, c'est reprendre là où on en était {#再跑一次}

Retapez `flower` dans le même répertoire et la première phrase change :

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

La ligne `<-` est la bannière de [réveil](../reference/glossary.md#唤醒) : elle indique l'état actuel de ce répertoire.
Il ne réinterroge pas sur les exigences et ne redéfinit pas les objectifs ; c'est pareil si le processus a été tué ou la machine redémarrée.
La phrase que vous dites à ce moment-là est ajoutée à `需求.md` et **déclenche une nouvelle dérivation de la liste de verdicts** —
sans cela, le juge lirait encore l'ancienne liste et ce que vous venez d'ajouter n'entrerait pas du tout dans le verdict.
Détails et coût (le contexte ne cesse de croître) dans [Continuité](../guide/continuity.md).

Pour ne pas reprendre, tapez `/new` : les exigences, les objectifs et la [lignée](../reference/glossary.md#血缘) du segment précédent
sont **déplacés** dans `notes/archive/<时间戳>/` (pas supprimés), puis tout repart de zéro.

## Dans un script, sans surveillance {#脚本}

La demande peut aussi être passée directement en argument ; les options se placent avant ou après, indifféremment :

```bash
flower "帮我做一个 X"                      # la demande en argument
flower --rounds 5 "帮我做一个 X"           # option avant
flower "帮我做一个 X" --rounds 5           # option après, équivalent
echo "帮我做一个 X" | flower --timeout 0   # pipe vers l'entrée standard, tout automatique
```

On peut aussi ne donner que des options sans demande — `flower --clarify-only` vous demandera d'abord ce que vous voulez faire avant de continuer.

**Pourquoi la voie « appuyer sur Entrée puis saisir » existe toujours.** Cette paire de guillemets sur la ligne de commande est un pur fardeau. Vécu en vrai :
le guillemet fermant tapé en chinois `”`, zsh attendant indéfiniment le vrai guillemet fermant (tombé dans l'invite de continuation `dquote>`),
ce qui ressemble à un programme figé alors qu'il n'a jamais démarré. `flower` lancé nu lit l'entrée standard, sans analyse du shell :
guillemets chinois, espaces, points d'exclamation, retours à la ligne se tapent tous directement. Le pipe passe par la même entrée —
quand l'entrée standard n'est pas un terminal, il n'affiche pas d'en-tête d'invite et lit directement une ligne.

!!! danger "Sans surveillance, il faut donner explicitement `--timeout 0`"
    Dans un pipe, sous `nohup` ou en CI, personne ne peut répondre aux questions. Sans `--timeout 0` : la première question est passée pour cause
    d'« entrée fermée », mais **chaque question suivante attend les 1800 secondes complètes** — quelques questions font quelques heures de tournage à vide,
    et pendant ce temps ça brûle de l'argent.
    `--timeout 0` fait échouer immédiatement toutes les questions en renvoyant « personne n'a répondu », et il continue en jugeant seul.
    Quand l'entrée standard n'est pas un terminal, flower affiche d'abord un avertissement :
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Si ça ne démarre pas {#冒烟}

Si `flower` ne réagit pas, signale une erreur d'identifiants, ou si la sortie est visiblement fausse, vérifiez d'abord identifiants et binaire
isolément, avec le tir le moins cher possible. Un seul agent, outils en lecture seule, un tir pour voir si les deux bouts communiquent :

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Ce fragment | Ce que c'est |
|---|---|
| `once` | Lance un agent unique une fois : pas de clarification, pas d'objectif, pas de délégation |
| `-w PATH` | Répertoire de travail de l'agent. Sans lui, c'est le répertoire courant |
| `-v` | Affiche avant le démarrage la configuration d'identifiants effective ; du token, seuls les 4 premiers caractères restent |

`once` ne donne par défaut que trois outils — `Read`, `Glob`, `Grep` : il ne peut rien écrire, donc ce tir est bon marché.
Mesure réelle : Opus 5 avec une fenêtre d'un million via une passerelle tierce, **le prix plancher d'un tour est $0.1741** ; les modèles moins chers descendent plus bas.
La section « vérifier que l'installation est bonne » de la page [Installation](install.md) lance exactement cette commande.

Si ça passe, voici la forme obtenue — les chiffres et le texte diffèreront, **pas les icônes** :

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 19 位)
ANTHROPIC_BASE_URL = https://your-gateway.example.com
ANTHROPIC_MODEL = claude-opus-5[1m]
- 验一下凭证…
  ~ 先看目录结构,再挑一两个文件读
  * Glob **/*.py
  * Read README.md
  这是一个用 Rust 写的命令行 HTTP 压测工具。
  - 累计 $0.00 · 0:00
  + 完成 4 轮 · $0.0932 · 用时 0:00
```

Deux choses à repérer :

- Les premières lignes sont la configuration effective affichée par `-v`. **Une passerelle erronée se voit du premier coup d'œil** — c'est la raison d'être principale de cette option.
- Le `$` de la ligne `+ 完成` est réel ; `累计` et `用时` valent constamment 0 sur le chemin `once`
  (un nouveau renderer est créé à chaque événement, l'état ne s'accumule pas).

Si ce tir passe, identifiants, passerelle, nom de modèle et binaire embarqué sont tous corrects : le problème est ailleurs. S'il ne passe pas, cela relève de l'installation :
retour à [Installation](install.md).

## Quoi lire ensuite {#接下来}

| Ce que vous voulez savoir | À lire |
|---|---|
| Ce que veulent dire tous ces mots à l'écran | [Concepts fondamentaux](concepts.md) |
| Toutes les sous-commandes et options, sans exception | [Référence de la ligne de commande](../reference/cli.md) |
| Pourquoi il commence par un tas de questions, et comment lui en faire poser moins | [Clarification préalable](../guide/clarify.md) |
| Qui décide si « c'est fini », et comment s'écrit la liste de verdicts | [Gardien d'objectif](../guide/goal.md) |
| Pourquoi un second run dans le même répertoire reprend le fil | [Continuité](../guide/continuity.md) |
| Ce qu'il fait quand le contexte est plein (ce n'est pas un compact) | [Handoff](../guide/handoff.md) |
| Identifiants, passerelle, nom de modèle, variables d'environnement | [Référence de configuration](../reference/config.md) |
| Remplacer le terminal, brancher Web / TUI / tout automatique | [Couche d'interaction](../guide/interaction.md) |
| Se passer des trois étapes fournies et écrire son propre workflow | [Concevoir un workflow](../guide/workflow.md) · [Python API](../reference/api.md) |
| Ce qui s'est réellement passé pendant un long run | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| La définition exacte d'un terme | [Glossaire](../reference/glossary.md) |
