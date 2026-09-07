# Démarrage rapide

Cette page vous emmène de « c'est installé » à « j'ai fait un vrai run, et je comprends ce qui s'affiche à l'écran ». Quatre sections, à faire dans l'ordre :
d'abord le tir le moins cher possible pour prouver que les identifiants et le binaire passent, puis un workflow complet sans une ligne de code,
ensuite apprendre à intervenir pendant qu'il tourne, enfin le mettre dans un script et le laisser tourner sans surveillance.

Un seul prérequis : `flower` est installé, dans le PATH, avec des identifiants configurés. Si ce n'est pas encore fait, voir [Installation](install.md).

## Étape 1 : vérifier avec le tir le moins cher {#冒烟}

Ne lancez pas le workflow complet d'emblée. Tirez d'abord un coup avec un seul agent et des outils en lecture seule, pour prouver que les identifiants et le binaire passent des deux côtés :

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Ce bout | Ce que c'est |
|---|---|
| `once` | Un run d'un seul agent : pas de clarification, pas d'objectif, pas de délégation |
| `-w PATH` | Répertoire de travail de l'agent. Sans lui, c'est le répertoire courant |
| `-v` | Affiche la configuration d'identifiants effective avant de démarrer ; du token, seuls les 4 premiers caractères restent |

`once` ne donne par défaut que trois outils — `Read`, `Glob`, `Grep` — il ne peut rien écrire, donc ce tir est bon marché.
Repère mesuré : Opus 5 avec une fenêtre d'un million via une passerelle tierce, **le prix plancher d'un tour est de $0.1741** ; les modèles moins chers descendent plus bas.

!!! tip "Si vous arrivez de la page d'installation, sautez ce passage"
    La section « vérifier que c'est bien installé » de la page [Installation](install.md) lance exactement cette commande. Si elle est passée, continuez ;
    ce qui suit explique seulement comment lire sa sortie.

Après exécution, vous devriez voir cette forme — les chiffres et le texte varieront, **les icônes non** :

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

Quatre choses à reconnaître, tout le reste en dépend :

- Les premières lignes sont la configuration effective affichée par `-v`. **Une passerelle mal branchée se voit du premier coup d'œil** — c'est la raison principale d'être de ce flag.
- `- 验一下凭证…` est une vraie sonde API avant le démarrage. Si les identifiants sont refusés, il affiche `! 凭证被拒:…` et vous demande sur-le-champ si vous voulez reconfigurer ;
  s'il n'y a pas de connexion, il affiche `(探针没打通:… —— 当作网络问题,照常开跑)` et **ne** vous fait **pas** reconfigurer un token qui allait très bien.
- Les icônes sont toujours en ASCII : `~` réflexion, `*` appel d'outil, `>` délégation, `+` succès, `x` échec, `?` question, `<-` reprise.
  Pas d'emoji — les emoji et les caractères de filet déclenchent un repli de glyphes dans le terminal ; en pratique, deux terminaux ont planté. **Tous les exemples de terminal de cette documentation
  utilisent ce jeu ASCII, identique à ce qui s'affiche sur votre écran.**
- Le `$` de la ligne `+ 完成` est réel ; `累计` et `用时` valent toujours 0 sur le chemin `once`
  (chaque événement recrée un renderer, l'état ne s'accumule pas).

Si ce tir passe, les identifiants, la passerelle, le nom de modèle et le binaire embarqué sont tous corrects. S'il échoue, c'est un problème d'installation : retour à [Installation](install.md).

## Étape 2 : un workflow complet sans code {#跑一次}

Pas besoin d'écrire de code, et **pas besoin de guillemets dans le shell**. Allez dans le répertoire de votre projet et tapez simplement :

```bash
cd /path/to/your/project
flower
```

Il vous demande ce que vous voulez faire, le curseur s'arrête sur `>` :

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Cette ligne est lue sur l'entrée standard, **sans passer par le shell** — guillemets typographiques, espaces, points d'exclamation se tapent directement.

Après Entrée, il déroule trois étapes. Chaque barre `==` à l'écran est une frontière d'[étape](../reference/glossary.md#步骤),
et le `1/3` à droite est la progression :

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

Trois endroits méritent un regard de plus :

- Les deux dernières lignes `+ 完成` ne sont pas un doublon. La première est le tour de travail, la seconde est le tour de **verdict** —
  le verdict tourne dans sa propre session, mais **n'ouvre pas de nouvelle barre `==`**, parce que c'est un tour interne à l'étape `干活`.
  Dans le [manifeste de run](../reference/glossary.md#运行清单), il s'appelle `干活·判定#1`.
- Le `$` d'une ligne `+ 完成` est l'argent **de ce tour-là**, `用时` est la durée totale **depuis le démarrage** : deux mesures différentes.
- Les lignes d'état du type `- 上下文 … · 累计 … · …` ne suivent que le [thread principal](../reference/glossary.md#主线程) ;
  le contexte des subagents n'y entre pas. Les appels d'outils des subagents sont affichés par défaut, indentés derrière une barre `|` ;
  **ce qu'ils disent** demande `-v` pour être visible — c'est du terrain, pas de la décision.

### Ce que sont ces trois étapes {#三步}

| L'étape à l'écran | Qui l'exécute | Ce qu'elle fait | Figée dans | Détails |
|---|---|---|---|---|
| `确认需求` | [Clarificateur](../reference/glossary.md#确认者) | Ne fait que poser des questions, ne touche à rien, **jusqu'à ce que ce soit clair, sans limite de tours** ; produit à la fin un [brief](../reference/glossary.md#需求确认书) en quatre parties | `.flower/notes/需求.md` | [Clarification préalable](../guide/clarify.md) |
| `设定目标` | [Juge](../reference/glossary.md#判定者) | Traduit le brief en « objectif + checklist de verdict », chaque entrée devant être vérifiable sur-le-champ | `.flower/notes/目标.md` | [Gardien d'objectif](../guide/goal.md) |
| `干活` | Le [coordinateur](../reference/glossary.md#协调者) délègue à des [subagents](../reference/glossary.md#subagent) | Le coordinateur découpe le travail, délègue, lit les rapports, décide ; à la fin de chaque tour, un juge **qui n'a pas participé au travail** tranche indépendamment « est-ce fini ou non » ; si ce n'est pas atteint, ça repart | Le code lui-même | [Gardien d'objectif](../guide/goal.md) |

Les deux premières étapes sont la concrétisation des deux mécanismes [clarification préalable](../reference/glossary.md#前置确认) et [gardien d'objectif](../reference/glossary.md#目标看守) ;
la troisième est le segment qu'ils encadrent ensemble. Par défaut, au plus 3 tours de verdict (`--rounds`),
et `--no-goal` désactive tout — une fois désactivé, « il dit que c'est fini » vaut vraiment fini.

Le verdict n'a que trois conclusions possibles : atteint, pas atteint, **invérifiable dans cet environnement**. Les deux dernières sont des conclusions distinctes —
« impossible de vérifier ici » ne passe jamais en succès, il s'arrête et vous demande.

Un run complet n'est pas bon marché. Repères mesurés : [HT002](../cases/ht002.md) installe et fait tourner un projet existant sur macOS,
4 étapes, environ 1 heure, **$38.24** ; [HT001](../cases/ht001.md) écrit un IDE de terminal depuis zéro,
**10.4 heures, $171.62**. Pour voir d'abord ce qu'il va demander avant de décider d'aller plus loin, utilisez `--clarify-only`.

### Comment répondre aux questions {#答提问}

Le bloc qui commence par `?` est une question qu'il vous pose ; trois façons de répondre :

- **Taper un numéro** (`1` / `2` / `3`) — sélectionne cette option, l'écran répond une ligne `+ <选中的那条>`.
- **Taper du texte** — réponse libre, pas nécessairement parmi les options.
- **Appuyer sur Entrée** — passer, le laisser trancher seul, l'écran répond une ligne `. 已跳过`.

Par défaut, il vous attend 1800 secondes (`--timeout`). Si personne ne répond, il affiche
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」`, puis continue ; il ne se bloque pas.
Le nombre de questions est **illimité par défaut** (`--asks` vaut `-1`) ; une valeur positive devient un quota dur, et une fois épuisé il affiche `! 提问额度用完`.

### Relancer, c'est reprendre là où c'était {#再跑一次}

Retapez `flower` dans le même répertoire, et la première phrase change :

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

La ligne `<-` est la bannière de [réveil](../reference/glossary.md#唤醒), elle rapporte l'état actuel de ce répertoire.
Il ne repassera pas l'interrogatoire des besoins, ni ne refixera l'objectif ; que le processus ait été tué ou la machine redémarrée, c'est pareil.
La phrase que vous tapez alors est ajoutée à `需求.md` et **déclenche une re-dérivation de la checklist de verdict** —
sans re-dérivation, le juge lirait toujours l'ancienne checklist et ce que vous venez d'ajouter n'entrerait pas dans le verdict.
Détails et coût (le contexte ne fait que grossir) dans [Continuité](../guide/continuity.md).

Si vous ne voulez pas reprendre, tapez `/new` : les besoins, l'objectif et la [lignée](../reference/glossary.md#血缘) du segment précédent
sont **déplacés** dans `notes/archive/<时间戳>/` (rien n'est supprimé), puis tout repart de zéro.

## Étape 3 : vous pouvez encore parler pendant qu'il tourne {#插话}

Il y a toujours, tout en bas de l'écran, une ligne de saisie. Ce n'est pas décoratif — elle est effacée avant chaque sortie et redessinée après,
donc elle **ne remonte jamais dans les logs**. Deux libellés, selon qu'il y a ou non une question en attente :

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Sans question en attente, vous pouvez faire deux choses.

**Taper une phrase = ajouter une exigence.** Il n'est pas interrompu ; il la verra à la prochaine consultation de sa boîte de réception. L'accusé de réception ressemble à ça :

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

« Ajouté au brief » est important : cette phrase atterrit en même temps dans `需求.md`, donc elle survit aux frontières d'étape —
l'étape suivante est une nouvelle session qui ne lit que les artefacts figés ; sans écriture sur disque, ce qui est dit n'existe pas.

**Commencer par `?` = poser une question en passant.** Il ouvre une session en lecture seule pour vous répondre, avec seulement les 60 derniers événements et
ce qui se trouve dans le [workbench](../reference/glossary.md#工作台). Cette voie de dérivation est exécutée par l'[oracle](../reference/glossary.md#旁路顾问), plafonnée par défaut à 12 tours / $0.5 :

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Jetable après réponse** — cet échange n'entre pas dans le contexte du run en cours, et son coût n'entre pas dans le manifeste de run principal ;
il est enregistré à part sous `runs/aside/`. Poser une question n'affecte donc pas le run, et vous n'avez pas à regretter cette dépense.

!!! warning "Le `？` pleine largeur ne compte pas, il faut un `?` demi-largeur"
    La détection d'une question de dérivation ne reconnaît que le `?` **demi-largeur** (ASCII `0x3f`). Le `？` pleine largeur produit par défaut par les IME chinois n'est pas reconnu —
    cette ligne est traitée comme « ajouter une exigence » et part dans la boîte de réception, **sans erreur** ; simplement, la réponse que vous attendez ne viendra jamais.
    C'est une coquille dans le code, déjà consignée dans la liste des défauts ; en attendant le correctif, basculez votre IME en anglais avant de taper `?`.

Au passage, Ctrl+C : en cours de run, la première pression **interrompt ce tour et vous laisse dire quelque chose**, ce n'est pas une sortie.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Il faut une seconde pression pour vraiment sortir. (Sur le tout premier prompt `要做什么?`, Ctrl-C sort directement et affiche `已取消`.)

## Étape 4 : dans un script {#脚本}

La demande peut aussi être passée directement en argument, et les options peuvent se placer avant ou après :

```bash
flower "帮我做一个 X"                      # la demande en argument
flower --rounds 5 "帮我做一个 X"           # option avant
flower "帮我做一个 X" --rounds 5           # option après, équivalent
echo "帮我做一个 X" | flower --timeout 0   # entrée standard via pipe, entièrement automatique
```

Ne donner que des options sans demande fonctionne aussi — `flower --clarify-only` vous demandera d'abord ce que vous voulez faire, puis continuera.

**Pourquoi la voie « Entrée puis saisie » existe toujours.** Cette paire de guillemets en ligne de commande est un pur fardeau. Vécu en vrai :
le guillemet fermant a été tapé en chinois `”`, zsh a attendu indéfiniment le vrai guillemet fermant (tombé dans le prompt de continuation `dquote>`),
on aurait dit que le programme était bloqué, alors qu'il n'avait jamais démarré. En lançant `flower` nu, la lecture se fait sur l'entrée standard, sans passer par le shell :
guillemets typographiques, espaces, points d'exclamation, retours à la ligne se tapent tous directement. La voie pipe passe par la même entrée —
quand l'entrée standard n'est pas un terminal, il n'affiche pas d'en-tête de prompt et lit directement une ligne.

!!! danger "Sans surveillance, il faut passer explicitement `--timeout 0`"
    Dans un pipe, sous `nohup`, en CI, personne ne peut répondre aux questions. Sans `--timeout 0` : la première question est passée pour cause d'
    « entrée fermée », **puis chaque question suivante attend les 1800 secondes complètes** ; quelques questions font des heures de tournage à vide,
    et pendant ce temps ça brûle de l'argent.
    `--timeout 0` fait échouer immédiatement toutes les questions avec « personne n'a répondu », et il continue en tranchant lui-même.
    Quand l'entrée standard n'est pas un terminal, flower affiche d'abord un rappel :
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Quoi lire ensuite {#接下来}

| Vous voulez savoir | Lisez |
|---|---|
| Ce que veulent vraiment dire ces mots à l'écran | [Concepts fondamentaux](concepts.md) |
| Toutes les sous-commandes et options, sans exception | [Référence CLI](../reference/cli.md) |
| Pourquoi il commence par une salve de questions, et comment lui en faire poser moins | [Clarification préalable](../guide/clarify.md) |
| Qui tranche « est-ce fini », et comment s'écrit la checklist de verdict | [Gardien d'objectif](../guide/goal.md) |
| Pourquoi un second run dans le même répertoire reprend le fil | [Continuité](../guide/continuity.md) |
| Ce qu'il fait quand le contexte est plein (ce n'est pas un compact) | [Passation](../guide/handoff.md) |
| Identifiants, passerelle, nom de modèle, variables d'environnement | [Référence de configuration](../reference/config.md) |
| Remplacer le terminal, brancher du Web / TUI / du tout-automatique | [Couche d'interaction](../guide/interaction.md) |
| Se passer des trois étapes fournies et écrire son propre workflow | [Concevoir un workflow](../guide/workflow.md) · [API Python](../reference/api.md) |
| Ce qui s'est réellement passé pendant un vrai long run | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| La définition exacte d'un terme | [Glossaire](../reference/glossary.md) |
