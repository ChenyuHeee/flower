# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Un framework d'agents long-horizon portable, bâti sur le Claude Agent SDK.</p>

<p class="fl-hero__sub">Sans sacrifier les capacités de Claude Code, en faire un agent spécialisé qu'on peut emporter, dont on personnalise l'interaction, et qui tient plusieurs jours.
L'agent sur le thread principal ne fait que décider ; tout le travail manuel part vers des subagents ;
le besoin est clarifié avant de commencer, et c'est un autre rôle qui juge si c'est fait ou non.
Le comportement est identique d'une machine à l'autre — il ne lit pas la configuration de la machine hôte, il apporte ses propres identifiants.</p>

[Démarrage rapide](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>coût d'un run</span></div>
<div class="fl-stat"><b>10.4 heures</b><span>en continu, reprise seule après une coupure réseau</span></div>
<div class="fl-stat"><b>185.9K</b><span>pic de contexte du thread principal, aucun compact du début à la fin</span></div>
<div class="fl-stat"><b>94.8 %</b><span>des caractères de texte tombent dans les subagents</span></div>
</div>

Ces quatre chiffres viennent de [HT001](cases/ht001.md) — le run où un agent a écrit, à partir de zéro et sous flower, un IDE de terminal.

## Installer {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Détecte automatiquement `uv` / `pipx` / `pip` et installe la commande `flower`. Il suffit d'avoir Python ≥ 3.10, ni Node,
ni la CLI Claude Code. Une fois installé, faites `cd` dans n'importe quel répertoire de projet et tapez `flower` : au premier lancement il vous demande une clé API
ou une adresse de passerelle, configurée une fois et stockée dans `~/.config/flower/.env`, valable partout ; si Claude Code est déjà installé et configuré sur la machine,
il emprunte directement ce token, sans même poser la question. Étapes complètes et dépannage : voir [Installation](getting-started/install.md).

## Il vous protège de quatre familles d'échecs {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarification préalable](guide/clarify.md) {#前置确认}

Peur que le résultat ne soit pas ce que vous vouliez — avant de commencer, un rôle qui ne fait que poser des questions, sans rien produire, interroge jusqu'à ce que ce soit clair, puis gèle le besoin dans un document
que chaque étape suivante lit pour démarrer.
</div>

<div class="fl-card" markdown>
### [Gardien d'objectif](guide/goal.md) {#目标看守}

Peur qu'il annonce « c'est fait » alors que ça ne l'est pas — à la fin de chaque tour de travail, un autre rôle juge de façon indépendante : atteint, on avance ; non atteint, on renvoie ;
invérifiable dans cet environnement, on s'arrête et on demande à un humain.
</div>

<div class="fl-card" markdown>
### [Continuité](guide/continuity.md) {#接续}

Peur de tout recommencer après un crash au bout de plusieurs heures — retapez `flower` dans le même répertoire et vous reprenez là où vous en étiez, y compris si le processus a été tué
ou la machine redémarrée ; vous n'avez aucun id à retenir.
</div>

<div class="fl-card" markdown>
### [Passation](guide/handoff.md) {#换代}

Peur qu'un contexte plein soit écrasé en un résumé — la session courante rédige elle-même un document de passation lisible et modifiable par un humain, qu'une nouvelle session reprend,
sans compact.
</div>

</div>

## Ce qui le rend « long-horizon » {#长程}

Le [coordinateur](reference/glossary.md#协调者) sur le thread principal ne contient que de la décision, il n'a accès ni à `Write` ni à `Edit` —
écrire du code, lancer les tests, chercher de la documentation partent tous vers des [subagents](reference/glossary.md#subagent) ;
les essais-erreurs du subagent vont dans une **autre** transcript, le thread principal ne reçoit qu'un rapport d'au plus 30 lignes.
Sur les 10.4 heures du run HT001, **94.8 % des caractères de texte sont tombés dans les subagents**,
et sur 1 893 appels d'outils manuels, 32 seulement sont entrés dans le champ de vision du coordinateur.
D'où un thread principal qui n'atteint 185.9K qu'au 70ᵉ tour, sans qu'aucun compact ne se produise — comment cette couche est faite, et quelles sont les trois autres,
voir [Économie du contexte](guide/context.md).

## Ça a vraiment tourné {#真的跑过}

- **[HT001](cases/ht001.md)** — écrire un IDE de terminal à partir de zéro. $171.62 / 10.4 heures /
  contexte du thread principal monté à 185.9K, 12 212 lignes de code produit livrées, une coupure réseau en cours de route, reprise et fin toute seule.
- **[HT002](cases/ht002.md)** — l'installer et le faire tourner sur macOS. $38.24 / environ 1 heure, première fois avec le gardien d'objectif ;
  le programme a bel et bien démarré, et pourtant le verdict est **non atteint**, remonté à l'humain.

Les deux pages écrivent aussi ce qui ne tient pas debout : dans HT001, l'agent s'est trompé sur un critère de sa propre recette,
dans HT002, `git clone && make && ./cppide` a pris une heure. Chaque chiffre est recalculable depuis `runs/manifest.json`
et `sessions.db` — ce sont des enregistrements bruts, pas de la promotion.

## Par où commencer {#从哪读起}

- **Envie de lancer tout de suite** — [Démarrage rapide](getting-started/quickstart.md) : dépensez d'abord vingt centimes pour valider vos identifiants,
  puis déroulez un workflow en trois étapes sans écrire une ligne de code.
- **Envie de comprendre les concepts d'abord** — [Concepts clés](getting-started/concepts.md) : run, étape, session, les cinq rôles,
  le tout en cinq minutes.
- **Envie de l'intégrer à votre propre code** — [API Python](reference/api.md) : `Runtime`, `Step`, les cinq fabriques de rôles,
  les signatures et valeurs par défaut de 62 symboles publics.
