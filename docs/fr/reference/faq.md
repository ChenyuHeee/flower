# Questions fréquentes et dépannage

Quand quelque chose casse, on ne sait pas quel module est en cause — on sait seulement ce qu'on
voit. Cette page est donc organisée par **symptôme observé**, pas par sous-système.

Chaque entrée a la même structure : **symptôme** (ce que vous voyez réellement) → **cause** →
**que faire**.

Cinq de ces entrées sont des **défauts connus**, pas des choix de conception. Elles disent
explicitement qu'il s'agit d'un bug, donnent le lien vers l'issue et le contournement — elles ne
les font pas passer pour des intentions.

## Installation impossible / ne démarre pas {#装不上}

La procédure d'installation complète est dans [install.md](../getting-started/install.md#一句话安装).
Cette section ne couvre que les cas « c'est installé, mais la commande ne part pas ».

### Version de Python inférieure à 3.10 {#python-版本}

**Symptôme** : des erreurs de syntaxe apparaissent pendant l'installation, ou pip annonce
directement qu'aucune version ne satisfait la contrainte.

**Cause** : flower exige Python ≥ 3.10. La seule dépendance d'exécution est `claude-agent-sdk`,
et le binaire natif est dans sa wheel — donc un échec d'installation vient presque toujours de la
version de l'interpréteur, pas du réseau.

**Que faire** : commencez par identifier dans quel interpréteur vous installez.

```bash
python3 --version
```

En dessous de 3.10, changez d'interpréteur avant d'installer. Le `python3` fourni par le système
n'est souvent pas celui vers lequel pointe `python` dans votre terminal ; vérifier la version
avant coûte moins cher que diagnostiquer après
(voir [install.md](../getting-started/install.md#装之前确认-python)).

### Installé, mais `flower: command not found` {#command-not-found}

**Symptôme** :

```text
zsh: command not found: flower
```

**Cause** : le paquet est installé, mais le répertoire qui contient le script exécutable généré
n'est pas dans le `PATH`. Ce n'est pas la même chose que « pas installé » — si
`python3 -c "import flower"` ne lève rien, le paquet est bon.

**Que faire** : le shebang du script `flower` est un chemin absolu, donc un lien symbolique dans
un répertoire déjà présent dans le `PATH` suffit ; rien à sourcer.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS : le PATH a été ajouté comme le disait `install.sh`, et toujours command not found {#macos-path}

!!! warning "Problème connu ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Ce conseil échoue précisément sur la machine qui en a besoin.

**Symptôme** : sur macOS, après avoir lancé `install.sh` et ajouté `~/.local/bin` au `PATH` comme
l'indique sa dernière ligne, puis rouvert le terminal, `flower` reste command not found.

**Cause** : lorsqu'on tombe sur le repli pip, le pip de macOS installe les scripts exécutables
dans `~/Library/Python/3.X/bin`, alors que `install.sh` demande d'ajouter `~/.local/bin`. Les
deux répertoires ne correspondent pas, et suivre le conseil ne sert à rien.

??? note "Dans quel ordre `install.sh` choisit la méthode d'installation, et le texte exact du message"

    La priorité comporte quatre branches, pas deux (`install.sh:35-56`) :

    ```text
    1. uv présent        → uv tool install --force
    2. sinon pipx présent → pipx install --force
    3. sinon             → curl astral.sh/uv/install.sh pour amorcer uv, puis installer avec uv si ça marche
    4. amorçage échoué   → "$PY" -m pip install --user --upgrade    ← c'est cette branche qui pose problème
    ```

    Le texte exact du message final sur le PATH (`install.sh:62-68`, affiché seulement si
    `command -v flower` ne trouve rien) :

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` est codé en dur à `$HOME/.local/bin` (`install.sh:63`). C'est correct pour les
    branches 1 et 3 — uv installe bien là ; **seule la branche 4, le repli pip, ne correspond pas
    sur macOS**. Ce piège n'apparaît donc que sur les machines où les trois premières branches
    ont échoué.

**Que faire** : ne devinez pas le répertoire, demandez-le à l'interpréteur.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Ajoutez le répertoire affiché au `PATH`, ou faites-en un lien symbolique vers `~/.local/bin` :

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip n'installent pas le même flower {#三种装法}

**Symptôme** : `flower` fonctionne, mais les modifications du code source n'ont aucun effet ; ou
la mise à jour laisse l'ancienne version ; ou deux terminaux de la même machine se comportent
différemment.

**Cause** : les trois méthodes placent le paquet et le script exécutable à des endroits
différents, et c'est le premier trouvé dans le `PATH` qui est exécuté.

??? note "Où atterrit chacune des trois méthodes"

    | Méthode | Script exécutable | Quand l'utiliser |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Pour modifier le code source. Effet immédiat |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Utilisation seule, dans un environnement isolé |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Repli. Répertoire : voir l'entrée précédente |

**Que faire** : identifiez d'abord lequel s'exécute, puis décidez lequel modifier.

```bash
which -a flower                      # liste tous les homonymes présents dans le PATH
head -1 "$(which flower)"            # le shebang pointe vers l'interpréteur : le paquet est dans cet environnement
```

Pour modifier le code source, utilisez venv + `-e .`, et ne le faites pas cohabiter avec une
installation `uv` / `pipx` — en cas de cohabitation, le coût de diagnostic dépasse largement celui
d'une réinstallation (voir [install.md](../getting-started/install.md#从源码装)).

## Identifiants et passerelles {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptôme** :

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Cause** : flower isole la configuration de la machine hôte avec `setting_sources=[]` ; les
identifiants doivent être fournis explicitement. L'ordre de recherche complet est dans
[config.md](config.md#凭证查找优先级).

**Que faire** : écrivez-les dans le `.env` à la racine du dépôt, ou dans l'environnement du
processus.

```bash
cp .env.example .env        # renseigner ANTHROPIC_AUTH_TOKEN ou ANTHROPIC_API_KEY
```

`.env` est déjà dans le gitignore. Pour les conteneurs, voir [deploy.md](deploy.md#凭证).

### Il affiche « flower ne lit pas `~/.claude/settings.json` » — cette phrase est fausse {#settings-json}

**Symptôme** : quand les identifiants ne sont pas configurés, `env.py:192` affiche :

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Cause** : cette phrase ne correspond pas au code. `env.py:56-75` **lit bel et bien**
`~/.claude/settings.json`, en n'y prenant que les champs d'identifiants, comme dernier niveau de
repli — c'est exactement ce que `install.sh` met en avant. Cette phrase n'est affichée qu'après
que le repli a échoué à trouver quoi que ce soit ; elle ne fait donc rien échouer, mais elle
amène à conclure que « flower ne peut pas utiliser le token de mon Claude Code », ce qui est faux.
Consigné dans l'[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Que faire** : si Claude Code est installé sur la machine, inutile de redemander des
identifiants, le repli les récupérera tout seul
(voir [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Si vous voyez réellement cette phrase, c'est que ce fichier ne contient pas non plus de champ
d'identifiant exploitable — écrivez un `.env` comme dans l'entrée précédente.

### Impossible de savoir quels identifiants et quel endpoint sont réellement actifs {#生效值}

**Symptôme** : vous avez modifié `.env` mais les requêtes partent toujours vers l'ancienne
passerelle ; ou vous ne savez pas dire quel modèle est utilisé.

**Cause** : les identifiants et l'endpoint ont plusieurs sources (environnement du processus,
`.env`, repli) ; qui l'emporte ne se lit pas dans un fichier de configuration mais à l'exécution.

**Que faire** : lancez une fois avec `-v`. Au démarrage, `describe()` est affiché : la `BASE_URL`
effective et le mapping de modèles, token masqué.

```bash
flower -v
```

Tableau complet des options dans [cli.md](cli.md#全局开关), tableau complet des variables dans
[config.md](config.md#环境变量).

### Un `KEY=` laissé dans `.env` empêche définitivement les sources suivantes de le remplir {#空值占位}

**Symptôme** : le token est exporté dans l'environnement du processus, `.env` contient aussi la
ligne `ANTHROPIC_AUTH_TOKEN=`, et l'erreur « identifiants manquants » persiste.

**Cause** : une valeur vide reste une affectation. Le `KEY=` de la source de priorité supérieure
**occupe** la clé, et les sources de priorité inférieure ne la remplissent plus ; or
`check_credentials()` (défini en `env.py:184`) teste « valeur non vide », d'où le message de
manquant. « Occupée » et « manquante » sont deux choses différentes, mais le symptôme est
identique — c'est ce qui rend ce cas si difficile à repérer soi-même.

**Que faire** : supprimez la ligne entière, ne laissez pas de valeur vide.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # liste toutes les lignes à valeur vide
```

Après suppression, revérifiez les valeurs effectives avec `-v`. Les règles d'analyse sont dans
[config.md](config.md#env-解析).

### Passerelle tierce : la connexion passe, mais le premier tour échoue {#网关}

**Symptôme** : 401 / 403 ; ou un nom de modèle inexistant ; ou un [handoff](glossary.md#换代) dès
le départ, avec une erreur mentionnant le « plancher de démarrage ».

**Cause** : trois familles d'erreurs de configuration, aux symptômes distincts.

??? note "Trois erreurs de configuration de passerelle, et comment les reconnaître"

    | Symptôme | Le plus souvent | Où agir |
    |---|---|---|
    | 401 / 403 | Les identifiants sont valides mais n'ont pas été émis par cette passerelle ; ou `BASE_URL` a un chemin manquant ou une barre oblique finale en trop | [config.md](config.md#凭证变量) |
    | Nom de modèle inexistant | La passerelle n'accepte que ses propres noms de modèles, le mapping n'est pas configuré | [config.md](config.md#模型变量) |
    | Handoff dès le départ, « plancher de démarrage » | Fenêtre trop petite : le seuil est sous le plancher de démarrage du rôle ([coordinator](glossary.md#协调者) : ~34k mesurés) | `--window`, voir [handoff.md](../guide/handoff.md#阈值怎么算) |

**Que faire** : affichez d'abord les valeurs effectives avec `-v` avant de toucher à la
configuration. La fenêtre mérite particulièrement d'être vérifiée — la passerelle de la machine de
développement est configurée en `claude-opus-5[1m]` ; en la comptant à 200 k comme au début, on
faisait un handoff tous les 150 k, alors qu'elle tient en réalité 950 k : **un facteur 5**, et un
travail [long-horizon](glossary.md#长程) se retrouve découpé en miettes.

---

## Ça tourne, mais le comportement est faux {#行为不对}

Dans ce groupe, aucun symptôme n'est une erreur : **la commande se termine, le code de sortie est
0, mais ce qu'elle fait est faux**. Les quatre premières entrées sont des défauts de code
confirmés, avec issue ouverte ; ce qui est donné ici est un contournement, pas un correctif. La
dernière est un choix de conception.

### `flower setup` lance un agent {#setup-跑成了-agent}

**Symptôme** : vous exécutez `flower setup` en pensant qu'il va demander l'endpoint et le token,
et il se met à demander « qu'est-ce qu'il faut faire », puis déroule tout le workflow go en
prenant le mot `setup` pour une description de tâche. À la fin, aucun identifiant n'a été écrit.

**Cause** : le `_CMDS` de `cli.py:937` ne liste que `"go"`, `"run"`, `"once"` — il manque
`"setup"`. L'étape qui complète la sous-commande par défaut réécrit donc l'argv `["setup"]` en
`["go", "setup"]` : `setup` est rétrogradé de sous-commande à premier argument positionnel de
`go`, c'est-à-dire à la demande elle-même.
**Aucun argv ne permet d'atteindre l'assistant de configuration.** Signalé en
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**Que faire** : coupez avec Ctrl-C et écrivez directement le fichier de configuration. `setup` ne
faisait de toute façon qu'écrire dans ce fichier :

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Les noms de variables complets et l'ordre de recherche des identifiants sont dans
[config.md](config.md#凭证变量).
Ensuite, lancez `flower -v` depuis n'importe quel répertoire : l'endpoint effectif affiché au
démarrage sert de vérification.

### Le `?` pleine chasse ne déclenche pas les questions à l'oracle {#全角问号}

**Symptôme** : vous tapez `?这个目录能删吗` dans l'invite de saisie selon la syntaxe décrite dans
[questions à l'oracle](cli.md#旁路问答), et au lieu de solliciter l'[oracle](glossary.md#旁路顾问),
la phrase est prise pour une réponse à la question en cours, ou rangée telle quelle dans la boîte
de réception.

**Cause** : `cli.py:907` enchaîne deux tests `startswith("?")`, **avec le même caractère ASCII les
deux fois**. Selon l'intention du code, le second aurait dû tester le `?` pleine chasse. Les
méthodes de saisie chinoises produisent par défaut la forme pleine chasse — les principaux
utilisateurs de cette fonctionnalité sont donc exactement ceux qui ne peuvent pas s'en servir.
Signalé en [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Ce cas pollue la demande"
    Un `?` qui rate n'est ni signalé ni jeté. Il est traité comme une saisie ordinaire :
    pendant la phase de clarify, comme une réponse à la question en cours ; sinon, il part dans la
    boîte de réception.
    **Une phrase que vous vouliez seulement demander en aparté finit écrite dans le brief.** Si
    vous constatez l'erreur, corrigez immédiatement `.flower/notes/需求.md` : c'est ce fichier qui
    fait foi en aval.

**Que faire** : passez en demi-chasse pour taper `?`, ou tapez d'abord le `?` en demi-chasse puis
repassez en chinois pour le corps du message.

### Le coût cumulé de `once` reste toujours à `$0.00` et la durée à `0:00` {#once-计数为零}

**Symptôme** : `flower once` tourne du début à la fin et la ligne d'état en bas affiche en
permanence `累计 $0.00` en coût cumulé, avec un chronomètre bloqué à `0:00`, alors que le même
modèle sur le même travail donne des chiffres avec `go`.

**Cause** : le `render()` de `once` **crée un nouveau `Render` à chaque event reçu** ; les
accumulateurs sont reconstruits avec, et repartent donc de zéro à chaque fois. Les cumuls sont
remis à zéro en boucle, ce n'est pas une absence de comptage.
Signalé en [#14](https://github.com/ChenyuHeee/flower/issues/14).

**Que faire** : pour des chiffres justes, passez par `go`, ce chemin n'est pas affecté. Si vous
tenez à la forme mono-tour de `once` tout en voulant les comptes, consultez `runs/manifest.json`
après coup — le coût de chaque step y est consigné, et ce relevé-là est correct.
Détails dans [config.md](config.md#run-dir).

### Une skill placée dans `plugin/` n'est jamais chargée {#plugin-不加载}

**Symptôme** : vous avez écrit une skill selon
[deploy.md](deploy.md#写一个-skill完整例子), l'arborescence est correcte, mais l'agent se comporte
comme s'il ignorait totalement son existence — **aucune erreur, pas une ligne de log**.

**Cause** : `plugin/` n'est pas embarqué dans la wheel. Dans le paquet installé, `PLUGIN_DIR`
pointe vers `<site-packages>/plugin`, répertoire inexistant, et le test d'existence avant
chargement passe silencieusement son tour.
**Les trois chemins d'`install.sh` sont touchés** ; seul un dépôt cloné depuis les sources peut
charger les skills. Signalé en [#15](https://github.com/ChenyuHeee/flower/issues/15).

**Que faire** : vérifiez d'abord vers quoi le chemin est résolu.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Si ça affiche `False`, c'est ce cas. Pour utiliser des skills, il n'existe aujourd'hui qu'une
solution : **partir d'un clone des sources**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Un paquet installé avec `-e` pointe vers le répertoire cloné, `PLUGIN_DIR` tombe sur le vrai
`plugin/`, et la vérification ci-dessus affiche alors `True`.

### `-T` ne change rien sur `go` {#trim-与-go}

**Symptôme** : vous ajoutez `-T` à `flower go`, et avec ou sans, le comportement est strictement
identique, comme si l'option était cassée.

**Cause** : **c'est voulu, ce n'est pas un défaut.** Le chemin `go` active le
[trim](glossary.md#裁剪) par défaut ; l'intention exprimée par `-T` est déjà satisfaite, la
redonner ne change donc rien. L'option réellement utile sur ce chemin est l'inverse,
`--no-trim` — il faut être explicite pour désactiver le trim. `-T` n'est une option significative
que pour `run` et `once`.

**Que faire** : pour vérifier que le trim est bien actif sur `go`, regardez l'affichage de
démarrage avec `-v`, ne jugez pas à la présence ou à l'absence de `-T` ; pour le désactiver,
passez `--no-trim`. La sémantique complète des options est dans [cli.md](cli.md#全局开关).

## Il dit que c'est fini, mais ce n'est pas fini {#没做完}

Le [goal guard](../guide/goal.md) existe précisément pour arrêter ce genre de cas — le worker a un
biais d'optimisme systématique : il sait ce qu'il a fait, pas ce qu'il a oublié. Mais le guard
lui-même se trompe, et ses erreurs ont une direction régulière. Les cinq entrées ci-dessous sont
séparées entre « il a laissé passer ce qu'il ne fallait pas » et « il ne laisse jamais passer ».

### Il dit « impossible à vérifier ici », puis il laisse passer {#无法达成不是未达成}

**Symptôme** : le verdict indique « impossible de vérifier ce point dans l'environnement actuel,
considéré comme atteint », et le workflow continue.

**Cause** : le [judge](glossary.md#判定者) a confondu « impossible à atteindre » et « non
atteint ». Ce sont **deux verdicts différents**, et c'est tout le propos de
[Trois verdicts, pas deux](../guide/goal.md#三个结论不是两个) :
« non atteint » renvoie au travail, « impossible à atteindre » **s'arrête et interroge l'humain**,
qui choisit d'accepter, de changer l'objectif, ou de dire que le jugement est faux.
Avec seulement « atteint / non atteint », un objectif en réalité irréalisable fait tourner le
coordinator tour après tour jusqu'à épuisement du budget.

**Que faire** : **« je ne peux pas le vérifier ici » ne doit jamais valoir « atteint »**. Dans les
`instructions` du judge, dites nommément ce qui compte comme irréalisable dans votre contexte,
pour qu'il rende « impossible à atteindre » quand c'est le cas.
Si vous ne voulez vraiment pas être interrompu par une question, passez `--timeout 0` : en cas
d'impossibilité, l'exécution s'arrête, la raison reste sur le disque, au lieu de passer en
douce.

### Il lit le code source et déclare que c'est fait {#判产出物}

**Symptôme** : le motif du verdict dit « X est déjà implémenté dans le code », « la signature de
la fonction est conforme », alors que ni l'artefact compilé, ni la sortie de commande, ni le
service en cours d'exécution n'ont été touchés.

**Cause** : le judge a été orienté vers le code source. On
[juge l'artefact, pas le code source](../guide/goal.md#判的是产出物不是源码) — qu'un code ait l'air
correct et que la chose livrée soit utilisable sont deux questions distinctes. La première est
déjà ce dont le worker est convaincu ; s'en convaincre une seconde fois ne produit aucune
information nouvelle.

**Que faire** : les critères de verdict doivent être des assertions sur l'**artefact**. « La
fonction d'export est implémentée » ne compte pas ; « exécuter `./app export out.csv`, `out.csv`
contient un en-tête à 3 colonnes » compte. C'est à l'étape de rédaction des objectifs qu'il faut
l'écrire ainsi, sinon le judge devra combler lui-même les entrées vagues.

### Le judge ne peut pas exécuter de commandes, alors il lit le Makefile et laisse passer {#判定者不能跑命令}

**Symptôme** : l'objectif est « produire un binaire exécutable sous Linux », le verdict est
positif. Vous lancez `file` vous-même : l'artefact est un Mach-O, pas un ELF.

**Cause** : le judge est par défaut en `judge(can_run=False)`, il ne dispose que de
**`Read` / `Glob` / `Grep`**. Ces trois outils lisent des fichiers, mais **ne peuvent exécuter ni
`file`, ni `./app --version`**. Faute de mieux, il lit le Makefile, voit dans la branche Darwin
une compilation croisée, et en conclut que la condition est remplie.
Il n'a pas menti, il a simplement **trouvé ce qui ressemblait le plus à une preuve dans les
limites de ses capacités**.

??? note "Quand faut-il impérativement activer `can_run`"
    Le critère est simple : **si l'objectif contient des mots du type « la chose construite », il
    faut l'activer.**

    - Artefacts : binaire, image, archive, données générées — activer
    - Comportements : le service démarre, la commande retourne 0, la sortie correspond à un motif — activer
    - Texte pur : la documentation est-elle écrite, tel champ a-t-il été ajouté au schéma — pas besoin

    En ligne de commande, c'est `--judge-can-run`. En câblage manuel, l'écriture diffère selon le
    point d'entrée, mais tout retombe sur le même paramètre de `judge()` :

    | Point d'entrée | Comment le passer | Source |
    |---|---|---|
    | `judge()` | `can_run=` est un paramètre en bonne et due forme | `roles.py:361` |
    | `with_goal()` | `can_run=` est un paramètre, transmis à `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **pas de paramètre `can_run`**, mais il tombe dans `**spec_kw`, et cette ligne est justement `judge(..., **spec_kw)` — ça arrive à destination | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, converti en `with_goal(can_run=…)` ; c'est le chemin de `--judge-can-run` | `starter.py:105` → `:196` |

    Le prix à payer : le judge exécute réellement des commandes, un tour de verdict est plus lent
    et plus cher ; en échange, il vérifie la **situation réelle**, pas sa notice.
    Voir [Le judge peut-il exécuter des commandes](../guide/goal.md#判定者能不能跑命令).

**Que faire** : si l'objectif porte sur un artefact, activez `--judge-can-run`. Sinon, imposez-vous
comme contrainte d'écriture des critères que « lisible suffit à juger » — un critère qu'on ne peut
pas formuler ainsi est un critère qui exige, par nature, d'exécuter une commande.

### La liste de verdict fait une quinzaine d'entrées, et elle ne passe jamais {#清单长度}

**Symptôme** : chaque tour est renvoyé, avec une longue liste de manques, qui s'allonge à mesure
qu'on corrige, et le travail ne se termine pas.

**Cause** : la liste a été écrite selon « à quel point je veux être rigoureux », pas selon
« combien ce travail a de modes de défaillance ».
[La longueur de la liste est dictée par le nombre de modes de défaillance](../guide/goal.md#清单的长度由有多少种失败方式决定) :
pour une tâche du type `git clone && make && ./app`, **trois à cinq entrées suffisent** — la
construction réussit, ça démarre, c'est utilisable.
Dans le dérapage réel décrit dans
[HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了), une tâche « installer le dépôt
et le faire tourner » avait été écrite en **15 entrées** : seulement 5 vérifiaient qu'une chose
fonctionnait, 6 vérifiaient le respect du processus, et 4 étaient **invérifiables par principe**.

**Que faire** : modifiez `.flower/notes/目标.md`, c'est ce fichier qui sert de base au verdict.
Passez chaque entrée en revue en demandant « à quel mode de défaillance celle-ci correspond-elle »,
et supprimez celles sans réponse. L'étape de définition des objectifs signale de toute façon les
entrées invérifiables ; ne les gardez pas de force.

### Des limites écrites comme des critères de verdict {#边界不是判定项}

**Symptôme** : la liste contient des entrées du type « n'a jamais exécuté `brew install` », « n'a
modifié aucun fichier hors du répertoire du projet », et le judge, pour prouver son innocence, va
inspecter la mtime de `~/.zshrc` ou vérifier si le répertoire `.flower/` a été touché.

**Cause** : les limites et les critères de verdict contraignent des choses différentes ; les
mélanger est la cause principale de l'incident HT002
([cause racine n°1](../cases/ht002.md#根因一边界被当成了判定项)).

| | Contraint quoi | Comment s'y conformer |
|---|---|---|
| **Limites** | **Comment vous travaillez** (« installer uniquement dans le répertoire du projet », « ne pas toucher au code métier ») | En **ne les franchissant pas**, pas en se justifiant après coup |
| **Critères de verdict** | **Ce qui est livré** (« est-ce que ça démarre », « est-ce que le résultat est correct ») | Par vérification sur place |

Les limites sont justement la partie que la phase de clarify encourage à remplir. Les recopier une
à une dans la liste revient à ajouter un contrôle par limite, et la plupart de ces contrôles sont
invérifiables — et une entrée invérifiable entraîne tout le tour de verdict dans son échec.

**Que faire** : laissez les limites dans la section « limites » du brief, respectez-les en ne les
franchissant pas, et ne les mettez pas dans la liste de verdict. Si une trace est vraiment
nécessaire, une phrase suffit — **ne les découpez pas en six entrées**.

---

## Contexte et coût {#上下文与花费}

Dans une exécution long-horizon, contexte et argent sont un seul et même problème : quand le
contexte sature, c'est soit un handoff, soit l'explosion de l'étape ; et tout ce qui est répété à
chaque tour est repayé à chaque tour suivant.

### En plein milieu, il ouvre une nouvelle session et annonce un « handoff » {#换代打断}

**Symptôme** dans le flux d'events apparaît un `handoff`, avec `payload["phase"]` d'abord `near`
puis `done`, un tour supplémentaire consacré à écrire le
[handoff document](glossary.md#交接书), après quoi le travail reprend normalement.

**Cause** le contexte approche du seuil. flower **ne compacte pas** — il écrit l'état de la
session courante dans un handoff document en cinq sections et démarre une nouvelle session qui le
lit et poursuit. Le [compact](glossary.md#压缩) efface au passage les informations les plus
coûteuses, comme « les pistes qui ne mènent nulle part », alors que le handoff document est
explicite, posé sur le disque et modifiable à tout moment : c'est ce fichier que lit la session
qui reprend.

**Que faire** c'est le chemin normal, rien à faire. Un handoff n'est pas un retry — `attempts`
n'augmente pas (il compte les échecs), le session_id retiré est consigné dans
`StepResult.retired`, et le `session_id` exposé est toujours celui du successeur encore vivant
(voir [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Pour revenir à l'auto-compact du SDK, utilisez `--no-handoff`.

??? note "D'où vient le seuil, et pourquoi la valeur par défaut est aussi agressive"
    `at = window - headroom`. `window` vaut **1 M par défaut**, déduit du nom du modèle : les noms
    contenant `haiku` comptent pour 200 k, les autres pour 1 M. `headroom` vaut 50k par défaut —
    l'auto-compact se déclenche à −33k, le handoff doit passer avant lui, et « écrire le
    handoff » demande encore un tour ; 50k satisfait les deux contraintes à la fois.

    Surestimer n'est pas une erreur dure : si la fenêtre réelle est plus petite, le seuil n'est
    jamais atteint, la requête est rejetée par l'API avec « prompt trop long », flower reconnaît ce
    signal (`handoff.is_overflow()`) et fait immédiatement un handoff avec un document dégradé
    assemblé mécaniquement ; l'étape n'échoue pas
    (voir [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Une mesure vaut la peine d'être citée : la passerelle de la machine de développement est
    configurée en `claude-opus-5[1m]`. En comptant 200 k comme au début, on faisait un handoff tous
    les 150 k, alors qu'elle tient en réalité 950 k — **un facteur 5**, et un travail long-horizon
    se retrouve découpé en miettes.

### Handoff dès le départ, et ça ne s'arrête plus {#一开局就换代}

**Symptôme** l'erreur mentionne le « plancher de démarrage », ou la même étape fait handoff sur
handoff jusqu'à buter sur `max_generations=8`.

**Cause** `window` est configuré trop petit, et le seuil est sous le plancher de démarrage du
rôle — mesuré à ~34k pour le coordinator, occupé rien que par le prompt système et l'index du
[workbench](glossary.md#工作台). La nouvelle session dépasse la ligne dès qu'elle ouvre la bouche,
d'où : écrire le handoff, changer de génération, redépasser, sans fin (un handoff ne consomme pas
de quota de retry, c'est voulu).

**Que faire** réglez `--window` sur la fenêtre réelle du modèle ; `-v` affiche l'endpoint et le
mapping de modèles effectifs. Une longue exécution normale n'atteint pas 8 générations ; si vous y
butez, c'est presque certainement cette cause, et le message d'erreur le dit d'ailleurs
directement
(voir [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Un symptôme apparenté est « le handoff est toujours dégradé » : la raison est écrite dans le champ
`errors` de `runs/manifest.json`.

### Ça s'arrête en cours de route en annonçant que le budget est épuisé {#预算到顶}

**Symptôme** le [step](glossary.md#步骤) s'arrête sans être terminé, motif : dépassement de coût.

**Cause** `AgentSpec(max_budget_usd=...)` est un **plafond dur**, pas un rappel indicatif ;
`Runtime.total_cost()` est le cumul de l'exécution en cours.

**Que faire** avant de relever le plafond, assurez-vous qu'il ne tourne pas à vide. Des tours
successifs renvoyés sans progression, c'est en général que le judge aurait dû rendre « impossible
à atteindre » et a rendu « non atteint » — un objectif en réalité irréalisable brûle le budget
jusqu'au bout
(voir [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Vérifiez d'abord que le travail avance, puis relevez le plafond.

### Pourquoi cette exécution coûte-t-elle si cher {#为什么这么贵}

**Symptôme** le coût dépasse largement les attentes, mais la sortie ne dit pas où l'argent est
passé.

**Cause** la comptabilité n'est pas dans le contexte du modèle. Le `session_id`, le coût, le
nombre de retries et le motif d'échec de chaque étape ne sont consignés que dans
`runs/manifest.json`, **en ajout inter-processus**. L'historique des retries et le texte brut des
erreurs ne sont là non plus qu'ici — le modèle ne les voit pas, et c'est intentionnel : si les
appels refusés s'empilent dans le contexte, le coordinator apprend que « Bash sera de toute façon
bloqué » et n'essaie même plus `git status` (`Runtime(keep_denials=1)` nettoie déjà par défaut, ne
l'augmentez pas).

**Que faire** ouvrez `runs/manifest.json` et rapprochez les coûts étape par étape (la disposition
sur disque est dans [config.md#磁盘布局](config.md#磁盘布局)).
Quelques valeurs mesurées, à titre de repère :

| | Coût |
|---|---|
| Plancher de démarrage d'un subagent (non amortissable) | ~4.3k tokens |
| Plancher de démarrage du coordinator | ~34k tokens |
| `tests/smoke.py` chaîne complète mono-agent | ~$0.21 |
| `tests/flow_demo.py` trois câblages de workflow | ~$0.39 |
| `tests/delegation.py` répartition + mesure de la distribution du contexte | ~$0.71 |
| `tests/isolation.py` trois issues, trois worktrees | ~$0.9 |

### Le contexte grossit plus vite que le travail n'avance {#上下文涨得快}

**Symptôme** chaque [task brief](glossary.md#任务书) répète la même liste de règles (« lis le
fichier avant de le modifier », « ne touche pas au code métier », « lance les tests après
modification »), alors que le [worker](glossary.md#执行者) les suit déjà.

**Cause** tout ce que dit le coordinator entre dans son propre transcript, et le transcript ne
fait que croître. Répéter les règles se paie ce tour-ci, **et se repaie à chaque tour suivant**.
Redire à quelqu'un ce qu'il sait déjà a un bénéfice nul et un coût permanent.

**Que faire** faites passer les règles dans le mécanisme, pas dans le discours de chaque tour : ce
qui peut s'exprimer via `allowed_tools`, la section « limites » du brief ou l'index du workbench
n'a pas à figurer dans le task brief ; le task brief ne dit que ce qui a changé ce tour-ci. La
répartition du travail est en soi la couche qui économise le plus
(voir [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Au resume, les gros anciens résultats d'outils peuvent être remplacés par des pointeurs de fichier
avec `-T`.

## Interruption et continuité {#中断与接续}

### Le processus a été tué, la machine a redémarré {#进程被杀}

**Symptôme** tout s'est arrêté en cours de route, et vous ne savez pas comment reprendre en
rouvrant un terminal.

**Cause** il n'y a rien à reprendre. La [lineage](glossary.md#血缘) (`runs/lineage.json`) consigne
nom d'étape → session_id, écrit sur disque à la fin de chaque étape, avec écriture dans un `.tmp`
puis remplacement atomique — être tué en cours de route ne laisse jamais un fichier à moitié écrit.

**Que faire** revenez dans le **même répertoire** et relancez `flower` : chaque étape reprend sa
session précédente, la demande n'est pas redemandée, les objectifs ne sont pas redéfinis, et même
les impasses déjà explorées par le coordinator sont encore en mémoire. Si vous n'avez rien à dire,
appuyez simplement sur Entrée
(voir [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
Le judge fait exception — ce n'est pas un `Step`, il est dépêché directement depuis le gate et ne
passe jamais par la lineage ; chaque tour lui donne donc un regard entièrement neuf.

### Ça repart de zéro à chaque fois, aucune reprise {#接不上}

**Symptôme** relancé dans le même répertoire, il repose toutes les questions sur la demande.

**Cause** trois formes de « ça ne correspond pas », et flower **repart silencieusement de zéro,
sans erreur** — la [continuité](glossary.md#接续) est un bonus, sa défaillance ne doit pas empêcher
de travailler :

- `runs/lineage.json` est absent, ou le `workspace` qu'il contient ne correspond pas à votre chemin actuel (c'est le cas si le répertoire a été copié ailleurs)
- la session n'est plus dans `runs/sessions.db` (base supprimée)
- le fichier de lineage est corrompu

**Que faire** vérifiez d'abord la présence de `runs/lineage.json` et l'exactitude de `workspace`
(le rôle des trois fichiers est décrit dans [../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
L'absence de continuité après un changement de répertoire est **intentionnelle** : `project_key`
est dérivé du chemin de l'espace de travail, et l'ancienne session est introuvable au nouvel
emplacement.

### Repartir à zéro sans perdre l'historique {#想重开}

**Symptôme** la demande a changé de direction et vous ne voulez pas qu'il continue sur la
précédente.

**Cause** le comportement par défaut est justement de continuer. Dans un répertoire déjà utilisé,
`flower "顺便支持代码块高亮"` n'est pas une nouvelle tâche, c'est une phrase de plus.

**Que faire** `--new`. C'est un **archivage, pas une suppression** : l'ancien contenu reste dans
`notes/archive/`.
Au [réveil](glossary.md#唤醒), une ligne indique d'abord la taille du contexte courant ; si elle
vous semble trop grosse, c'est aussi ce chemin qu'il faut prendre.

### Le réseau est coupé : ni erreur, ni progression {#断网}

**Symptôme** plus aucun nouvel event à l'écran, le processus est toujours vivant, on dirait un
blocage.

**Cause** une coupure réseau est traitée comme « attends un peu », pas comme un échec. flower
patiente : il sonde d'abord le DNS, puis le TCP, et ne reprend qu'une fois la connexion rétablie
(voir [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
Dans HT001, ce mécanisme a été validé par une panne réelle
(voir [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Que faire** attendez ; `-v` montre les sondes en cours. Les erreurs accumulées pendant l'attente
**n'entrent pas dans le contexte après la reprise** — elles ne sont consignées que dans
`runs/manifest.json`, et la session qui reprend voit une situation propre, sans être détournée par
une série de timeouts.

### Deux Ctrl-C consécutifs : la clôture n'est pas complète {#双重-ctrl-c}

**Symptôme** un arrêt par `kill` (SIGTERM) et deux Ctrl-C consécutifs ne laissent pas le même état.

**Cause** lacune connue. Un double Ctrl-C lève `KeyboardInterrupt` : dans `cli.py`, le `finally`
de `_drive` appelle `rt.close()`, mais **pas** `rt.rescue()` — seul le gestionnaire de
SIGHUP/SIGTERM appelle `rescue()`.

**Que faire** la lineage est préservée dans les deux cas (écriture atomique à la fin de chaque
étape), donc une relance reprend quand même, et cette lacune ne vous fait pas perdre de
progression. Pour une clôture complète, utilisez `kill <pid>` plutôt que de marteler Ctrl-C.

## Parallélisme et isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptôme** avec l'isolation activée, rien ne démarre : `not in a git repository`.

**Cause** `worker(..., isolate=True)` s'appuie sur git worktree pour donner à chaque agent une
copie privée ; si le workspace n'est pas un dépôt git, la copie ne peut pas être créée.

**Que faire** ce cas **ne dégrade pas silencieusement** — soit vous travaillez réellement dans un
dépôt, soit vous désactivez `isolate`. L'isolation garantit que « plusieurs agents modifient en
même temps sans voir l'arbre de travail des autres » ; elle ne garantit pas l'absence de conflits
de fusion.

### Un agent isolé ne peut pas écrire dans le workbench {#隔离写不进工作台}

**Symptôme** le subagent signale un « refus de permission d'écriture », scripts et artefacts ne
sont pas persistés ; ou bien les artefacts atterrissent dans un worktree et restent invisibles aux
autres agents.

**Cause** un worktree est une **copie privée** par agent, le workbench est une **couche partagée**
entre agents. Ce qui est partagé, placé dans un enclos privé, devient évidemment inaccessible aux
autres.

**Que faire** avec l'isolation activée, pointez le workbench **hors du dépôt** :

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Quand il est hors de l'espace de travail, `Runtime` accorde automatiquement l'autorisation via
`add_dirs` ; `Runtime(workbench=True)` s'en charge déjà, mais un `Workbench` construit à la main
doit obtenir cette autorisation lui-même.

!!! warning "Le workbench a deux emplacements par défaut, et ils diffèrent"
    `Workbench(workspace)` — c'est le chemin de la CLI et de `starter_flow()` — place le workbench
    dans `<workspace>/.flower` ;
    tandis que `Runtime(workbench=True)` (c'est-à-dire `-W`) le place dans `<run_dir>/workbench`,
    soit `runs/workbench`.
    Donc une exécution de `flower` vous donne un `.flower/`, alors qu'un appel à
    `Runtime(workbench=True)` en Python **non**.

### `flower` crée un `.flower/`, mais pas mon script maison {#两个工作台默认值}

**Symptôme** le brief est bien écrit dans `.flower/notes/需求.md`, mais le coordinator se comporte
comme s'il ne l'avait jamais lu ; **aucune erreur**.

**Cause** vous manipulez deux objets workbench. Le brief est écrit dans le répertoire A, tandis
que l'index injecté dans le prompt système scanne le répertoire B, et la promesse « savoir dès le
départ où se trouve le fichier de demande » **échoue silencieusement**. Les deux façons de se
tromper ne produisent aucune erreur : un `brief_path` assemblé à la main relativement au cwd du
processus n'est pas le même répertoire que le `<run_dir>/workbench` créé par `-W` ; et le récupérer
à rebours depuis `Runtime` ne marche pas non plus — `cli.py` appelle d'abord `main()` pour
construire le `Workflow`, et ne crée le `Runtime` qu'ensuite, quand `brief_path` est déjà figé.

**Que faire** construisez vous-même un `Workbench` et passez le **même objet** à la fois au
`Workflow` et au `Runtime` ; l'emplacement est alors verrouillé :

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` verrouille ce point : la 5e assertion vérifie que le brief apparaît bien
dans `prompt_block()`.
Par ailleurs, l'index n'est injecté que dans le prompt système du **coordinator** ; les subagents
n'en héritent pas (mesuré à $0.2461, `tests/prelude_live.py`) — les chemins doivent être relayés
par le coordinator, ils ne sont pas connus automatiquement de chaque subagent
(voir [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
