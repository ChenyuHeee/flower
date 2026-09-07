# FAQ et dépannage

Quand ça casse, on ne sait pas quel module est en cause — on sait seulement ce qu'on voit. Cette page
est donc organisée par **symptôme observé**, pas par sous-système.

Chaque entrée a la même structure : **symptôme** (ce que vous voyez réellement) → **cause** → **quoi faire**.

Cinq de ces entrées sont des **défauts connus**, pas des choix de conception. Elles disent explicitement
qu'il s'agit d'un bug, donnent le lien de l'issue et un contournement — elles ne les font pas passer
pour des décisions intentionnelles.

## Ça ne s'installe pas / ça ne démarre pas {#装不上}

La procédure d'installation complète est dans [install.md](../getting-started/install.md#一句话安装). Cette section
ne couvre que les cas « c'est installé, mais la commande ne démarre pas ».

### Version de Python inférieure à 3.10 {#python-版本}

**Symptôme** : une erreur de syntaxe pendant l'installation, ou pip qui annonce directement qu'aucune version
ne satisfait la contrainte.

**Cause** : flower exige Python ≥ 3.10. La seule dépendance d'exécution est `claude-agent-sdk`, dont le binaire
natif est embarqué dans sa wheel — un échec d'installation vient donc le plus souvent de la version de
l'interpréteur, pas du réseau.

**Quoi faire** : commencez par confirmer dans quel interpréteur vous installez.

```bash
python3 --version
```

En dessous de 3.10, changez d'interpréteur avant d'installer. Le `python3` fourni par le système n'est souvent
pas celui vers lequel pointe `python` dans votre terminal ; vérifier la version avant coûte moins cher que
déboguer après (voir [install.md](../getting-started/install.md#装之前确认-python)).

### Installé, mais `flower: command not found` {#command-not-found}

**Symptôme** :

```text
zsh: command not found: flower
```

**Cause** : le paquet est installé, mais le répertoire du script exécutable généré n'est pas dans le `PATH`.
Ce n'est pas la même chose que « pas installé » — si `python3 -c "import flower"` ne lève rien, le paquet est bon.

**Quoi faire** : le shebang du script `flower` est un chemin absolu ; un lien symbolique dans un répertoire déjà
présent dans le `PATH` suffit, sans avoir à sourcer quoi que ce soit.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS : j'ai ajouté le PATH comme l'indique `install.sh`, toujours command not found {#macos-path}

!!! warning "Problème connu ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Ce conseil tombe précisément à côté sur la machine qui en a besoin.

**Symptôme** : sur macOS, après avoir exécuté `install.sh` et suivi son message final en ajoutant
`~/.local/bin` au `PATH`, puis rouvert le terminal, `flower` reste command not found.

**Cause** : lorsqu'on retombe sur la voie de secours pip, le pip de macOS installe le script exécutable dans
`~/Library/Python/3.X/bin`, alors que `install.sh` demande d'ajouter `~/.local/bin`. Les deux répertoires ne
correspondent pas, suivre le message ne sert à rien.

??? note "Dans quel ordre `install.sh` choisit la méthode d'installation, et le texte exact de ce message"

    La priorité comporte quatre étapes, pas deux (`install.sh:35-56`) :

    ```text
    1. uv présent        → uv tool install --force
    2. sinon pipx présent → pipx install --force
    3. sinon             → curl astral.sh/uv/install.sh pour amorcer uv, puis installer avec uv
    4. amorçage échoué   → "$PY" -m pip install --user --upgrade    ← c'est celle-ci qui pose problème
    ```

    Le texte exact du message PATH final (`install.sh:62-68`, affiché uniquement si `command -v flower` échoue) :

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` est codé en dur à `$HOME/.local/bin` (`install.sh:63`). C'est correct pour les voies 1 et 3
    — uv installe bien là ; **seule la voie 4, le repli pip, tombe à côté sur macOS**. Le piège n'apparaît donc
    que sur les machines où les trois premières voies ont toutes échoué.

**Quoi faire** : ne devinez pas le répertoire, demandez-le à l'interpréteur.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Ajoutez le répertoire affiché au `PATH`, ou faites-en un lien symbolique vers `~/.local/bin` :

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip n'installent pas le même flower {#三种装法}

**Symptôme** : `flower` s'exécute, mais les modifications du code source n'ont aucun effet ; ou après une mise à
jour la version reste l'ancienne ; ou deux terminaux de la même machine se comportent différemment.

**Cause** : les trois méthodes placent le paquet et le script exécutable à des endroits différents ; c'est le
premier trouvé dans le `PATH` qui s'exécute.

??? note "Où atterrissent les trois méthodes"

    | Méthode | Script exécutable | Quand l'utiliser |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Pour modifier le code source. Effet immédiat |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Usage sans modification, environnement isolé |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Repli. Répertoire : voir l'entrée précédente |

**Quoi faire** : confirmez d'abord lequel s'exécute, puis décidez lequel modifier.

```bash
which -a flower                      # liste tous les homonymes présents dans le PATH
head -1 "$(which flower)"            # le shebang indique l'interpréteur, donc l'environnement du paquet
```

Pour modifier le code source, utilisez venv + `-e .`, sans cohabiter avec une installation `uv` / `pipx` — en
cas de cohabitation, le coût du diagnostic dépasse largement celui d'une réinstallation
(voir [install.md](../getting-started/install.md#从源码装)).

## Identifiants et passerelle {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptôme** :

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Cause** : flower isole la configuration de la machine hôte avec `setting_sources=[]` ; les identifiants doivent
être fournis explicitement. L'ordre de recherche complet est dans
[config.md](config.md#凭证查找优先级).

**Quoi faire** : écrivez-les dans le `.env` à la racine du dépôt, ou dans l'environnement du processus.

```bash
cp .env.example .env        # renseigner ANTHROPIC_AUTH_TOKEN ou ANTHROPIC_API_KEY
```

`.env` est déjà dans le gitignore. Pour les conteneurs, voir [deploy.md](deploy.md#凭证).

### Il dit « flower ne lit pas `~/.claude/settings.json` » — cette phrase est fausse {#settings-json}

**Symptôme** : lorsque les identifiants sont mal configurés, `env.py:192` affiche :

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Cause** : cette phrase ne correspond pas au code. `env.py:56-75` **lit bel et bien** `~/.claude/settings.json`,
en n'en prenant que les champs d'identifiants, comme dernier niveau de repli — c'est exactement ce que
`install.sh` met en avant. Cette phrase n'est affichée qu'après l'échec de ce repli, elle ne fait donc échouer
rien du tout ; mais elle amène à conclure que « flower ne peut pas utiliser le token de mon Claude Code », ce qui
est faux. Consigné dans l'[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Quoi faire** : si Claude Code est installé sur la machine, inutile de redemander des identifiants, le repli les
récupère tout seul (voir [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Si vous voyez réellement cette phrase, c'est que ce fichier ne contient aucun champ d'identifiant exploitable —
écrivez un `.env` comme indiqué à l'entrée précédente.

### Impossible de savoir quels identifiants et quel endpoint sont réellement actifs {#生效值}

**Symptôme** : le `.env` a été modifié mais les requêtes partent toujours vers l'ancienne passerelle ; ou vous ne
savez pas dire quel modèle est utilisé.

**Cause** : les identifiants et l'endpoint ont plusieurs sources (environnement du processus, `.env`, repli) ; le
gagnant ne se lit pas dans un fichier de configuration, il se lit à l'exécution.

**Quoi faire** : lancez une fois avec `-v`. Au démarrage, `describe()` est affiché : `BASE_URL` effective et
mapping de modèles, token masqué.

```bash
flower -v
```

Tableau complet des options dans [cli.md](cli.md#全局开关), tableau complet des variables dans
[config.md](config.md#环境变量).

### Un `KEY=` laissé dans `.env` empêche définitivement les sources suivantes de le remplir {#空值占位}

**Symptôme** : le token est exporté dans l'environnement du processus, le `.env` contient aussi la ligne
`ANTHROPIC_AUTH_TOKEN=`, et l'erreur « identifiants manquants » persiste.

**Cause** : une valeur vide reste une affectation. Le `KEY=` d'une source prioritaire **occupe** la clé, et les
sources de priorité inférieure ne la remplissent plus ; or `check_credentials()` (défini en `env.py:184`) teste
« valeur non vide », d'où le message de valeur manquante. « Occupée » et « manquante » sont deux choses
différentes, mais le symptôme est identique — c'est ce qui rend cette classe de problème si difficile à voir
soi-même.

**Quoi faire** : supprimez la ligne entière, ne laissez pas de valeur vide.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # liste toutes les lignes à valeur vide
```

Après suppression, revérifiez les valeurs effectives avec `-v`. Les règles d'analyse sont dans
[config.md](config.md#env-解析).

### Passerelle tierce : la connexion passe, mais le premier tour échoue {#网关}

**Symptôme** : 401 / 403 ; ou un nom de modèle inexistant ; ou un [handoff](glossary.md#换代) dès l'ouverture,
avec une erreur de « plancher de démarrage ».

**Cause** : trois erreurs de configuration distinctes, aux symptômes différents.

??? note "Trois erreurs de configuration de passerelle, comment les reconnaître"

    | Symptôme | Le plus souvent | Où agir |
    |---|---|---|
    | 401 / 403 | Les identifiants sont valides mais pas émis par cette passerelle ; ou `BASE_URL` manque un segment de chemin, ou a une barre oblique finale en trop | [config.md](config.md#凭证变量) |
    | Nom de modèle inexistant | La passerelle n'accepte que ses propres noms de modèles, le mapping n'est pas configuré | [config.md](config.md#模型变量) |
    | Handoff dès l'ouverture, erreur « plancher de démarrage » | Fenêtre trop petite : le seuil est en dessous du plancher de démarrage du rôle (mesuré à ~34k pour le [coordinateur](glossary.md#协调者)) | `--window`, voir [handoff.md](../guide/handoff.md#阈值怎么算) |

**Quoi faire** : affichez d'abord les valeurs effectives avec `-v` avant de toucher à la configuration. La fenêtre
mérite particulièrement d'être vérifiée — sur la machine de développement, la passerelle est configurée en
`claude-opus-5[1m]` ; en la comptant à 200 000 comme au début, on changeait de génération tous les 150 000 alors
qu'elle tient en réalité 950 000, soit **un facteur 5** ; le travail [long-horizon](glossary.md#长程) se retrouve
découpé en miettes.

---

## Ça tourne, mais le comportement est faux {#行为不对}

Dans ce groupe, aucun symptôme n'est une erreur : **la commande se termine, le code de sortie est 0, mais ce
qu'elle fait est faux.** Les quatre premières entrées sont des défauts de code confirmés, avec issue ouverte ;
ce qui est donné ici est un contournement, pas un correctif. La dernière est un choix de conception.

### `flower setup` lance un agent {#setup-跑成了-agent}

**Symptôme** : vous exécutez `flower setup` en pensant qu'il va demander l'endpoint et le token, et il se met à
demander « qu'est-ce qu'il faut faire », puis déroule le flux go complet en prenant le mot `setup` pour la
description de la tâche. À la fin, pas un caractère d'identifiant n'a été écrit.

**Cause** : le `_CMDS` de `cli.py:758` ne liste que `"go"`, `"run"`, `"once"`, et omet `"setup"`.
L'étape qui complète la sous-commande par défaut réécrit donc l'argv `["setup"]` en `["go", "setup"]` —
`setup` est rétrogradé de sous-commande au premier argument positionnel de `go`, c'est-à-dire à la demande
elle-même. **Aucun argv ne permet d'atteindre l'assistant de configuration.**
Signalé en [#11](https://github.com/ChenyuHeee/flower/issues/11).

**Quoi faire** : Ctrl-C, puis écrivez directement le fichier de configuration. Tout ce que faisait `setup`,
c'était écrire dans ce fichier :

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Les noms de variables complets et l'ordre de recherche des identifiants sont dans
[config.md](config.md#凭证变量).
Une fois écrit, lancez `flower -v` depuis n'importe quel répertoire : l'endpoint effectif affiché au démarrage
sert de vérification.

### Le `？` pleine chasse ne déclenche pas la question à l'oracle {#全角问号}

**Symptôme** : en suivant la syntaxe des [questions à l'oracle](cli.md#旁路问答), vous tapez
`？ce répertoire peut-il être supprimé` dans l'invite de saisie ; l'[oracle](glossary.md#旁路顾问) n'est pas
lancé, la phrase est prise pour une réponse à la question en cours, ou versée telle quelle dans la boîte de
réception.

**Cause** : `cli.py:733` enchaîne deux tests `startswith("?")`, **avec le même caractère ASCII les deux fois**.
Selon l'intention du code, le second aurait dû tester le `？` pleine chasse. Ce que produit par défaut une méthode
de saisie chinoise, c'est justement la version pleine chasse — les utilisateurs principaux de cette fonction sont
exactement ceux qui ne peuvent pas s'en servir. Signalé en
[#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Cette entrée pollue le besoin"
    Un `？` qui ne prend pas ne provoque aucune erreur et n'est pas non plus jeté. Il est traité comme une saisie
    ordinaire : pendant la phase de clarification, il est pris pour une réponse à la question en cours ; sinon il
    va dans la boîte de réception.
    **Une phrase que vous vouliez juste poser en aparté finit écrite dans le brief.** Si vous vous apercevez de
    l'erreur, corrigez `.flower/notes/需求.md` sur-le-champ : c'est ce fichier qui fait foi en aval.

**Quoi faire** : passez en demi-chasse pour taper `?`, ou tapez d'abord le `?` demi-chasse puis revenez au chinois
pour le corps de la phrase.

### Le coût cumulé de `once` reste à `$0.00` et le chrono à `0:00` {#once-计数为零}

**Symptôme** : `flower once` tourne du début à la fin, la ligne d'état en bas affiche en permanence
`累计 $0.00` et le chrono reste à `0:00`, alors que le même modèle sur le même travail donne des chiffres
avec `go`.

**Cause** : le `render()` de `once` **crée un nouveau `Render` à chaque événement reçu**, ce qui reconstruit
aussi les accumulateurs, qui repartent donc de zéro à chaque fois. Les cumuls sont remis à zéro en boucle, ils ne
sont pas absents de la comptabilité.
Signalé en [#14](https://github.com/ChenyuHeee/flower/issues/14).

**Quoi faire** : pour des chiffres exacts, passez par `go`, ce chemin n'est pas affecté. Si vous voulez la forme
mono-tour de `once` tout en voyant les comptes, consultez `runs/manifest.json` après coup — le coût de chaque
étape y est consigné, et cet enregistrement-là est correct.
Détails dans [config.md](config.md#run-dir).

### Un skill placé dans `plugin/` n'est jamais chargé {#plugin-不加载}

**Symptôme** : le skill est écrit comme dans [deploy.md](deploy.md#写一个-skill完整例子), la structure de
répertoires est correcte, mais l'agent se comporte comme s'il ignorait son existence — **aucune erreur, aucune
ligne de log**.

**Cause** : `plugin/` n'est pas empaqueté dans la wheel. Dans le paquet installé, `PLUGIN_DIR` pointe vers
`<site-packages>/plugin`, répertoire qui n'existe pas, et le test d'existence avant chargement passe
silencieusement.
**Les trois voies de `install.sh` sont toutes touchées** ; seul un dépôt cloné depuis les sources charge le skill.
Signalé en [#15](https://github.com/ChenyuHeee/flower/issues/15).

**Quoi faire** : vérifiez d'abord vers quoi le chemin est réellement résolu.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Si cela affiche `False`, c'est ce cas. Pour utiliser des skills, il n'existe aujourd'hui qu'une solution :
**exécuter depuis un clone des sources**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Un paquet installé avec `-e` pointe vers le répertoire cloné, `PLUGIN_DIR` tombe sur le vrai `plugin/`, et la
vérification ci-dessus affiche alors `True`.

### `-T` ne change rien sur `go` {#trim-与-go}

**Symptôme** : vous ajoutez `-T` à `flower go` ; avec ou sans, le comportement est strictement identique, comme
si l'option était cassée.

**Cause** : **c'est un choix de conception, pas un défaut.** La voie `go` active le
[trim](glossary.md#裁剪) par défaut ; l'intention exprimée par `-T` est déjà satisfaite, la redonner ne change
donc rien. Sur cette voie, l'option réelle est l'option inverse `--no-trim` — il faut l'indiquer explicitement
pour désactiver le trim. `-T` n'est une option significative que sur `run` et `once`.

**Quoi faire** : pour confirmer sur `go` que le trim est bien actif, regardez l'affichage de démarrage avec `-v`,
ne jugez pas à la présence ou l'absence de `-T` ; pour le désactiver, passez `--no-trim`. La sémantique complète
des options est dans [cli.md](cli.md#全局开关).

## Il dit que c'est fini, mais ce n'est pas fini {#没做完}

Le [gardien d'objectif](../guide/goal.md) existe exactement pour bloquer cette famille de cas — l'exécutant a un
biais d'optimisme systématique : il sait ce qu'il a fait, il ne sait pas ce qu'il a oublié. Mais le gardien
lui-même se trompe, et ses erreurs ont une direction régulière.
Les cinq entrées ci-dessous sont réparties entre « il laisse passer ce qu'il ne devrait pas » et « il ne laisse
jamais passer ».

### Il dit « impossible à vérifier ici », puis ça passe {#无法达成不是未达成}

**Symptôme** : le verdict indique « impossible à vérifier dans l'environnement actuel, considéré comme atteint »,
et le workflow continue.

**Cause** : le [juge](glossary.md#判定者) a fondu « impossible à atteindre » et « non atteint » en une seule
conclusion. Ce sont **deux conclusions différentes** ; c'est exactement le sujet de
[Trois conclusions, pas deux](../guide/goal.md#三个结论不是两个) :
« non atteint » signifie renvoyer au travail, « impossible à atteindre » signifie **s'arrêter et demander à
l'humain**, qui choisit d'accepter, de changer l'objectif, ou de dire que le juge s'est trompé.
Avec seulement deux conclusions « atteint / non atteint », un objectif réellement irréalisable fait tourner le
coordinateur à vide, tour après tour, jusqu'à épuisement du budget.

**Quoi faire** : **« je ne peux pas vérifier ici » ne doit jamais valoir « atteint ».** Dans les `instructions`
du juge, dites explicitement ce qui compte comme irréalisable dans votre contexte, pour qu'il rende
« impossible à atteindre » quand c'est le cas.
Si vous ne voulez vraiment pas être interrompu par une question, passez `--timeout 0` : en cas d'impossibilité,
il s'arrête net et la raison reste sur le disque, plutôt que de passer en fraude.

### Il lit le code source et déclare que c'est fait {#判产出物}

**Symptôme** : la justification du verdict dit « X est implémenté dans le code », « la signature de la fonction
est conforme », alors qu'aucun artefact de build, aucune sortie de commande, aucun service démarré n'a été touché.

**Cause** : le juge a été orienté vers le code source. [Ce qui est jugé, c'est le livrable, pas le code
source](../guide/goal.md#判的是产出物不是源码) — que le code ait l'air correct et que la chose livrée soit
utilisable sont deux questions distinctes. La première est déjà ce dont l'exécutant est convaincu ; en être
convaincu une fois de plus n'apporte aucune information nouvelle.

**Quoi faire** : les critères de verdict doivent être des assertions sur le **livrable**. « La fonction d'export
est implémentée » ne compte pas ; « exécuter `./app export out.csv`, `out.csv` a 3 colonnes d'en-tête » compte.
C'est dès l'étape de définition de l'objectif qu'il faut écrire ainsi, sinon le juge n'a qu'une liste vague à
compléter lui-même.

### Le juge ne peut pas exécuter de commande, alors il lit le Makefile et laisse passer {#判定者不能跑命令}

**Symptôme** : l'objectif est « produire un binaire exécutable sous Linux », le verdict est positif.
Vous faites un `file` vous-même : l'artefact est du Mach-O, pas du tout de l'ELF.

**Cause** : le juge est par défaut en `judge(can_run=False)`, il ne dispose **que de `Read` / `Glob` / `Grep`**.
Ces trois outils lisent des fichiers, **ils ne peuvent pas exécuter `file`, ni `./app --version`**.
Faute de mieux, il va lire le Makefile, voit dans la branche Darwin une compilation croisée, et en conclut que la
condition est remplie. Il n'a pas menti, il a simplement **trouvé, dans les limites de ses capacités, ce qui
ressemblait le plus à une preuve**.

??? note "Quand faut-il obligatoirement activer `can_run`"
    Le critère est simple : **dès que l'objectif contient des mots du type « la chose construite », il faut
    l'activer.**

    - Type artefact : binaire, image, archive, données générées — activer
    - Type comportement : le service démarre, la commande renvoie 0, la sortie correspond à un motif — activer
    - Type texte pur : la doc est-elle écrite, tel champ a-t-il été ajouté au schéma — inutile

    En ligne de commande, c'est `--judge-can-run`. En câblage manuel, l'écriture diffère selon le point d'entrée,
    mais tout retombe sur le même paramètre de `judge()` :

    | Point d'entrée | Comment le passer | Référence |
    |---|---|---|
    | `judge()` | `can_run=` est un paramètre en bonne et due forme | `roles.py:361` |
    | `with_goal()` | `can_run=` est un paramètre, transmis à `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **pas de paramètre `can_run`**, mais il tombe dans `**spec_kw`, et cette ligne est justement `judge(..., **spec_kw)` — il arrive donc à destination | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, converti en `with_goal(can_run=…)` ; c'est la voie de `--judge-can-run` | `starter.py:105` → `:196` |

    Le coût : le juge exécute réellement des commandes, un tour de verdict est plus lent et plus cher ; en échange,
    il vérifie la **situation réelle**, pas sa notice.
    Voir [Le juge peut-il exécuter des commandes](../guide/goal.md#判定者能不能跑命令).

**Quoi faire** : si l'objectif porte sur un artefact, activez `--judge-can-run`. Sinon, prenez « vérifiable par
simple lecture » comme contrainte dure pour écrire les critères — un critère qui ne peut pas s'écrire ainsi est
justement un critère qui exige l'exécution d'une commande.

### La liste de vérification fait une quinzaine de points et ne passe jamais {#清单长度}

**Symptôme** : chaque tour est rejeté, avec une longue liste d'écarts, qui s'allonge au fil des corrections ; le
travail ne se termine jamais.

**Cause** : la liste a été écrite selon « à quel point je veux être rigoureux », pas selon « de combien de façons
ce travail peut échouer ».
[La longueur de la liste est déterminée par le nombre de modes de défaillance](../guide/goal.md#清单的长度由有多少种失败方式决定) :
pour une tâche du type `git clone && make && ./app`, **trois à cinq points suffisent** — le build passe, ça
démarre, c'est utilisable.
Le vrai plantage raconté dans [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了) : une tâche
« installer le dépôt et le faire tourner » écrite en **15 points** — seulement 5 vérifiaient que la chose
fonctionne, 6 vérifiaient le respect des règles de procédure, et 4 étaient **invérifiables par principe**.

**Quoi faire** : modifiez `.flower/notes/目标.md`, c'est ce fichier qui sert de base au verdict. Reprenez chaque
point en demandant « à quel mode de défaillance celui-ci correspond-il » ; supprimez ceux sans réponse. L'étape de
définition de l'objectif signale de toute façon les critères invérifiables ; ne les gardez pas de force.

### Des limites écrites comme critères de verdict {#边界不是判定项}

**Symptôme** : la liste contient des points du type « n'a pas exécuté `brew install` », « n'a modifié aucun fichier
hors du répertoire du projet », et le juge, pour prouver son innocence, va inspecter la mtime de `~/.zshrc` et
vérifier si le répertoire `.flower/` a été touché.

**Cause** : les limites et les critères de verdict contraignent des choses différentes ; les mélanger est la cause
principale du plantage de HT002
([cause racine 1](../cases/ht002.md#根因一边界被当成了判定项)).

| | Contraint quoi | Comment s'y conformer |
|---|---|---|
| **Limites** | **Comment vous travaillez** (« installer uniquement dans le répertoire du projet », « ne pas toucher au code métier ») | En **ne les franchissant pas**, pas par une auto-justification a posteriori |
| **Critères de verdict** | **Ce qui est livré** (« est-ce que ça démarre », « le résultat est-il correct ») | Par vérification sur pièce |

Les limites sont précisément la section que la phase de clarification encourage à remplir. Les recopier une à une
dans la liste revient à ajouter une vérification par limite ajoutée — et la plupart de ces vérifications sont
impossibles ; un critère invérifiable fait échouer tout le tour de verdict avec lui.

**Quoi faire** : gardez les limites dans la section « limites » du brief, respectez-les en ne les franchissant pas,
ne les mettez pas dans la liste de vérification.
S'il faut vraiment en rendre compte, une phrase suffit, **ne les découpez pas en six points**.

---

## Contexte et coût {#上下文与花费}

Sur un run long-horizon, le contexte et l'argent sont le même problème : quand le contexte atteint le plafond,
c'est soit un handoff, soit l'explosion de l'étape ; et chaque phrase répétée à un tour donné est repayée à chaque
tour suivant.

### En plein milieu, il ouvre tout seul une nouvelle session en disant « handoff » {#换代打断}

**Symptôme** un `handoff` apparaît dans le flux d'événements, avec `payload["phase"]` d'abord `near` puis `done`,
un tour supplémentaire consacré à l'écriture du [document de handoff](glossary.md#交接书), puis le travail reprend
normalement.

**Cause** le contexte approche du seuil. flower **ne fait pas de compact** — il écrit l'état de la session
courante dans un document de handoff en cinq sections, puis démarre une nouvelle session qui le lit et poursuit.
Le [compact](glossary.md#压缩) effacerait au passage les informations les plus chères, comme « les pistes sans
issue », alors que le document de handoff est explicite, posé sur le disque et modifiable à tout moment : c'est ce
fichier que lit la session qui reprend.

**Quoi faire** c'est le chemin normal, rien à faire. Un handoff ne compte pas comme une nouvelle tentative —
`attempts` n'augmente pas (il compte les échecs), le session_id abandonné est consigné dans `StepResult.retired`,
et le `session_id` exposé est toujours celui du successeur encore vivant
(voir [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Pour vraiment revenir à l'auto-compact du SDK, utilisez `--no-handoff`.

??? note "D'où vient le seuil, et pourquoi la valeur par défaut est aussi agressive"
    `at = window - headroom`. `window` vaut **1 000 000 par défaut**, déterminé d'après le nom du modèle : un nom
    contenant `haiku` compte pour 200 000, tout le reste pour 1 000 000. `headroom` vaut 50k par défaut —
    l'auto-compact se déclenche à −33k, le handoff doit passer avant, et « écrire le document de handoff » demande
    encore un tour ; 50k satisfait ces deux contraintes à la fois.

    Surestimer n'est pas une erreur dure : si la fenêtre réelle est plus petite, le seuil n'est jamais atteint, la
    requête est rejetée par l'API pour « prompt trop long », flower reconnaît ce signal
    (`handoff.is_overflow()`) et effectue sur-le-champ un handoff avec un document dégradé assemblé
    mécaniquement ; l'étape n'échoue pas
    (voir [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Une mesure vaut d'être citée : sur la machine de développement, la passerelle est configurée en
    `claude-opus-5[1m]`. En la comptant à 200 000 comme au début, on changeait de génération tous les 150 000 alors
    qu'elle tient en réalité 950 000 — **un facteur 5**, et le travail long-horizon se retrouve découpé en miettes.

### Handoff dès l'ouverture, et ça ne s'arrête plus {#一开局就换代}

**Symptôme** l'erreur mentionne le « plancher de démarrage », ou la même étape enchaîne les handoffs jusqu'à
buter sur `max_generations=8`.

**Cause** `window` est configuré trop petit et le seuil passe sous le plancher de démarrage du rôle — mesuré à
~34k pour le coordinateur, consommé rien que par le prompt système et l'index du [workbench](glossary.md#工作台).
La nouvelle session dépasse la ligne dès sa première prise de parole, donc elle écrit un document de handoff,
change de génération, redépasse, indéfiniment (les handoffs ne consomment pas le quota de tentatives, c'est
intentionnel).

**Quoi faire** ajustez `--window` à la fenêtre réelle du modèle ; `-v` affiche l'endpoint et le mapping de modèles
effectifs. Un run long normal n'atteint pas 8 générations ; si c'est le cas, c'est presque certainement cette
cause, et le message d'erreur le dit directement
(voir [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Un symptôme apparenté est « le handoff est toujours dégradé » : la raison est écrite dans les `errors` de
`runs/manifest.json`.

### Ça s'arrête à mi-parcours en annonçant le plafond de budget {#预算到顶}

**Symptôme** l'[étape](glossary.md#步骤) s'arrête avant d'être terminée, au motif d'un dépassement de coût.

**Cause** `AgentSpec(max_budget_usd=...)` est un **plafond dur**, pas un simple rappel ; `Runtime.total_cost()` est
le total du run en cours.

**Quoi faire** avant de relever le plafond, assurez-vous qu'il ne tourne pas à vide. Des rejets tour après tour
sans le moindre progrès viennent en général d'un juge qui rend « non atteint » là où il devrait rendre
« impossible à atteindre » — un objectif réellement irréalisable brûle le budget jusqu'au bout
(voir [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirmez que le travail avance réellement, puis relevez le plafond.

### Pourquoi ce run coûte-t-il aussi cher {#为什么这么贵}

**Symptôme** le coût dépasse largement les attentes, mais la sortie ne dit pas où part l'argent.

**Cause** la comptabilité n'est pas dans le contexte du modèle. Le `session_id`, le coût, le nombre de tentatives
et la raison d'échec de chaque étape sont consignés uniquement dans `runs/manifest.json`, **en ajout entre
processus**. L'historique des tentatives et le texte brut des erreurs n'existent qu'ici — le modèle ne les voit
pas, et c'est intentionnel : si les appels refusés s'empilaient dans le contexte, le coordinateur apprendrait que
« de toute façon Bash sera bloqué » et n'essaierait même plus `git status`
(`Runtime(keep_denials=1)` est déjà quasi nul par défaut, ne l'augmentez pas).

**Quoi faire** ouvrez `runs/manifest.json` et rapprochez les coûts étape par étape (la disposition sur disque est
dans [config.md#磁盘布局](config.md#磁盘布局)). Quelques valeurs mesurées de référence :

| | Coût |
|---|---|
| Plancher de démarrage d'un subagent (non amortissable) | ~4.3k tokens |
| Plancher de démarrage du coordinateur | ~34k tokens |
| `tests/smoke.py`, chaîne complète mono-agent | ~$0.21 |
| `tests/flow_demo.py`, trois câblages de workflow | ~$0.39 |
| `tests/delegation.py`, répartition + mesure de la distribution du contexte | ~$0.71 |
| `tests/isolation.py`, trois issues dans trois worktrees | ~$0.9 |

### Le contexte grossit plus vite que le travail n'avance {#上下文涨得快}

**Symptôme** chaque [brief de tâche](glossary.md#任务书) répète la même consigne de discipline (« lire le fichier
avant de le modifier », « ne pas toucher au code métier », « lancer les tests après modification »), alors que
l'[exécutant](glossary.md#执行者) s'y conforme déjà.

**Cause** tout ce que dit le coordinateur entre dans son propre transcript, et un transcript ne fait que croître.
Redire la discipline coûte de l'argent à ce tour-ci, **et il faut la repayer à chaque tour suivant**. Redire à
quelqu'un ce qu'il sait déjà a un bénéfice nul et un coût permanent.

**Quoi faire** mettez la discipline dans le mécanisme, pas dans les paroles de chaque tour : ce qui peut
s'exprimer via `allowed_tools`, la section « limites » du brief ou l'index du workbench n'a pas à figurer dans le
brief de tâche ; celui-ci ne dit que ce qui a changé à ce tour. La répartition du travail est la couche qui
économise le plus
(voir [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Au moment du resume, les gros résultats d'outils anciens peuvent être remplacés par des pointeurs de fichiers avec
`-T`.

## Interruption et continuité {#中断与接续}

### Le processus a été tué, la machine a redémarré {#进程被杀}

**Symptôme** tout s'est arrêté en cours de route, et vous ne savez pas quoi faire pour reprendre après avoir
rouvert un terminal.

**Cause** il n'y a rien à récupérer. Le [lignage](glossary.md#血缘) (`runs/lineage.json`) enregistre nom d'étape →
session_id, écrit sur disque à la fin de chaque étape, avec écriture d'un `.tmp` puis remplacement atomique — une
mort en cours d'écriture ne laisse pas de fichier à moitié écrit.

**Quoi faire** revenez dans le **même répertoire** et relancez `flower` : chaque étape reprend sa session
précédente ; le besoin n'est pas redemandé, l'objectif n'est pas redéfini, et même les impasses déjà essayées par
le coordinateur restent en mémoire. Si vous n'avez rien à dire, appuyez simplement sur Entrée
(voir [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
Le juge est l'exception — ce n'est pas un `Step`, il est dépêché directement depuis le gate et ne passe jamais par
le lignage ; à chaque tour, c'est donc une paire d'yeux entièrement neuve.

### Ça repart de zéro à chaque fois, sans jamais reprendre {#接不上}

**Symptôme** en relançant dans le même répertoire, il redemande tout le besoin.

**Cause** trois formes de « ça ne correspond pas », et flower **retombe silencieusement sur un départ à zéro, sans
erreur** — la [continuité](glossary.md#接续) est un bonus, sa défaillance ne doit pas empêcher de travailler :

- `runs/lineage.json` est absent, ou le `workspace` qu'il contient ne correspond pas à votre chemin actuel (ce qui
  arrive dès que le répertoire a été copié ailleurs)
- la session n'est plus dans `runs/sessions.db` (base supprimée)
- le fichier de lignage est corrompu

**Quoi faire** vérifiez d'abord la présence de `runs/lineage.json` et la validité de son `workspace`
(le rôle des trois fichiers est décrit dans
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
L'absence de continuité après un changement de répertoire est **intentionnelle** : `project_key` est dérivé du
chemin de l'espace de travail, et les anciennes sessions sont introuvables au nouvel emplacement.

### Je veux repartir de zéro, mais sans perdre l'historique {#想重开}

**Symptôme** le besoin a changé de direction et vous ne voulez pas qu'il continue sur le lot précédent.

**Cause** le comportement par défaut est justement de continuer. Dans un répertoire déjà utilisé,
`flower "au passage, gérer la coloration des blocs de code"` n'est pas une nouvelle tâche, c'est une phrase de plus.

**Quoi faire** `--new`. Il **archive, il ne supprime pas** : l'ancien reste dans `notes/archive/`.
Au [réveil](glossary.md#唤醒), une ligne indique la taille du contexte courant ; si elle vous paraît trop grosse,
c'est aussi cette voie qu'il faut prendre.

### Le réseau est tombé, il n'affiche pas d'erreur et ne bouge pas {#断网}

**Symptôme** aucun nouvel événement à l'écran, le processus est toujours vivant, ça ressemble à un blocage.

**Cause** la coupure réseau est traitée comme « attendre un peu », pas comme un échec. flower reste suspendu et
attend : il sonde d'abord le DNS, puis le TCP, et ne continue qu'une fois la connectivité rétablie
(voir [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
Dans HT001, ce comportement a été validé par une panne réelle
(voir [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Quoi faire** laissez-le faire ; `-v` permet de voir les sondes tourner. Les erreurs accumulées pendant l'attente
**n'entrent pas dans le contexte après reprise** — elles ne se déposent que dans `runs/manifest.json`, et la
session qui reprend voit une situation propre, sans se laisser égarer par une série de timeouts.

### Deux Ctrl-C d'affilée : la clôture n'est pas complète {#双重-ctrl-c}

**Symptôme** arrêter par `kill` (SIGTERM) et enchaîner deux Ctrl-C ne laissent pas le même état sur disque.

**Cause** lacune connue. Le double Ctrl-C lève un `KeyboardInterrupt` : dans `cli.py`, le `finally` de `_drive`
appelle `rt.close()`, mais **pas** `rt.rescue()` — seuls les gestionnaires SIGHUP/SIGTERM appellent `rescue()`.

**Quoi faire** le lignage est préservé dans les deux cas (écriture atomique à la fin de chaque étape), donc une
relance reprend quand même ; cette lacune ne vous fait pas perdre de progression. Pour une clôture complète,
utilisez `kill <pid>` plutôt que de marteler Ctrl-C.

## Parallélisme et isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptôme** avec l'isolation activée, rien ne démarre, l'erreur est `not in a git repository`.

**Cause** `worker(..., isolate=True)` s'appuie sur les worktrees git pour donner à chaque agent une copie privée ;
si le workspace n'est pas un dépôt git, la copie ne peut pas être créée.

**Quoi faire** ce cas **ne dégrade pas silencieusement** — soit vous travaillez vraiment dans un dépôt, soit vous
désactivez `isolate`. L'isolation garantit que plusieurs agents modifient en parallèle sans voir l'arbre de
travail des autres ; elle ne garantit pas l'absence de conflit à la fusion.

### Un agent isolé ne peut pas écrire dans le workbench {#隔离写不进工作台}

**Symptôme** le subagent signale un « refus de permission d'écriture », les scripts et les livrables ne
s'écrivent pas ; ou bien les livrables atterrissent dans un worktree particulier, invisible des autres agents.

**Cause** le worktree est une **copie privée** par agent, le workbench est une **couche partagée** entre agents.
Ce qui est partagé, placé derrière une clôture privée, devient évidemment inaccessible aux autres.

**Quoi faire** avec l'isolation activée, pointez le workbench **hors du dépôt** :

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Placé hors de l'espace de travail, `Runtime` accorde automatiquement l'autorisation via `add_dirs` ;
`Runtime(workbench=True)` s'en charge déjà, mais un `Workbench` construit à la main exige que vous accordiez
l'autorisation vous-même.

!!! warning "Le workbench a deux emplacements par défaut, et ils diffèrent"
    `Workbench(workspace)` — c'est la voie de la CLI et de `starter_flow()` — place le workbench dans
    `<workspace>/.flower` ; tandis que `Runtime(workbench=True)` (autrement dit `-W`) le place dans
    `<run_dir>/workbench`, c'est-à-dire `runs/workbench`.
    Un run de `flower` vous donne donc un `.flower/` ; appeler `Runtime(workbench=True)` en Python **non**.

### `flower` crée un `.flower/`, mais pas mon script maison {#两个工作台默认值}

**Symptôme** le brief est bien écrit dans `.flower/notes/需求.md`, mais le coordinateur se comporte comme s'il ne
l'avait jamais lu ; **aucune erreur**.

**Cause** vous manipulez deux objets workbench. Le brief est écrit dans le répertoire A, tandis que l'index injecté
dans le prompt système parcourt le répertoire B ; la promesse « il sait dès l'ouverture où se trouve le fichier de
besoin » **échoue silencieusement**. Les deux façons de se tromper sont muettes : un `brief_path` assemblé à la
main relativement au cwd du processus et le `<run_dir>/workbench` créé par `-W` sont deux répertoires distincts ;
et le récupérer à l'envers depuis `Runtime` ne marche pas non plus — `cli.py` appelle d'abord `main()` pour
construire le `Workflow`, et ne crée le `Runtime` qu'ensuite, alors que `brief_path` est déjà figé.

**Quoi faire** construisez vous-même un `Workbench` et attachez le **même objet** au `Workflow` et au `Runtime` ;
l'emplacement est alors fixé :

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` verrouille ce point : la 5e assertion vérifie que le brief apparaît bien dans
`prompt_block()`. Par ailleurs, l'index n'est injecté que dans le prompt système du **coordinateur** ; les
subagents n'en héritent pas (mesuré à $0.2461, `tests/prelude_live.py`) — le chemin doit être transmis par le
coordinateur, il n'est pas connu automatiquement de chaque subagent
(voir [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
