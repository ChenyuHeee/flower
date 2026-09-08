# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Un framework d'agent long-horizon portable, bâti sur le Claude Agent SDK.</p>

<p class="fl-hero__sub">Sans sacrifier les capacités de Claude Code, on en fait un agent spécialisé qu'on peut emporter, dont on personnalise l'interaction, et qui tourne pendant des jours.
L'agent du main thread ne fait que décider ; tout ce qui se fabrique part chez des subagents ; le besoin est tiré au clair avant de commencer, et c'est un autre rôle qui juge si c'est fait ou non.
Changez de machine, le comportement reste le même — il ne lit pas les réglages de la machine hôte, il apporte ses propres identifiants.</p>

[Démarrage rapide](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>coût d'un run</span></div>
<div class="fl-stat"><b>10.4 heures</b><span>en continu, réseau coupé en route, reprise seul</span></div>
<div class="fl-stat"><b>185.9K</b><span>pic de contexte du main thread, aucun compact</span></div>
<div class="fl-stat"><b>94.8%</b><span>des caractères de corps de texte chez les subagents</span></div>
</div>

Ces quatre chiffres viennent de [HT001](cases/ht001.md) — le run où un agent a écrit de zéro un IDE de terminal sous flower.

## Une commande pour l'installer, sans Node {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Le script trouve tout seul `uv` / `pipx` / `pip` pour installer la commande `flower` ; il suffit d'avoir Python ≥ 3.10,
et le CLI Claude Code n'est même pas nécessaire. Une fois installé, faites `cd` dans n'importe quel répertoire de projet et tapez `flower` : la première fois, il vous demande une clé API
ou une adresse de passerelle ; configuré une fois, c'est enregistré dans `~/.config/flower/.env` et valable partout ; si Claude Code est déjà installé et configuré sur la machine,
il emprunte directement ce token, sans rien demander. Étapes complètes et dépannage : voir [Installation](getting-started/install.md).

## Il vous protège de quatre familles d'échecs {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Peur que le résultat ne soit pas ce que vous vouliez — avant de commencer, un rôle qui ne fait que poser des questions, sans rien fabriquer, interroge jusqu'à ce que ce soit clair, puis fige le besoin dans un document
que chaque étape suivante lit en ouverture.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Peur qu'il annonce « c'est fait » alors que non — à la fin de chaque tour de travail, un autre rôle juge indépendamment : atteint, on continue ; non atteint, on renvoie ;
invérifiable dans cet environnement, on s'arrête et on demande à un humain.
</div>

<div class="fl-card" markdown>
### [Continuité](guide/continuity.md) {#接续}

Peur que ça plante après des heures et qu'il faille tout reprendre — retapez `flower` dans le même répertoire et il reprend là où il en était, même si le processus a été tué
ou la machine redémarrée, sans que vous ayez à retenir le moindre id.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Peur que le contexte plein soit écrasé en un résumé — la session courante rédige elle-même un handoff document lisible et modifiable par un humain, qu'une nouvelle session reprend,
sans compact.
</div>

</div>

## Ce qui le rend « long-horizon » {#长程}

Le [coordinateur](reference/glossary.md#协调者) du main thread ne porte que des décisions : il n'a accès ni à `Write` ni à `Edit` —
écrire du code, lancer les tests, chercher de la doc, tout part chez des [subagents](reference/glossary.md#subagent) ;
les essais et erreurs du subagent vont dans **une autre** transcript, et le main thread ne reçoit qu'un rapport de 30 lignes maximum.
Sur les 10.4 heures du run HT001, **94.8% des caractères de corps de texte sont tombés chez les subagents**,
et sur 1,893 appels d'outils qui fabriquent quelque chose, seuls 32 sont entrés dans le champ de vision du coordinateur.
D'où un main thread qui n'atteint 185.9K qu'au bout de 70 tours, sans qu'aucun compact ne se produise — comment cette couche est faite, et quelles sont les trois autres :
voir [Économie du contexte](guide/context.md).

## Les enregistrements bruts de deux vraies longues courses {#真的跑过}

- **[HT001](cases/ht001.md)** — écrire un IDE de terminal de zéro. $171.62 / 10.4 heures /
  contexte du main thread monté à 185.9K, 12,212 lignes de code produit livrées, une coupure réseau en route, reprise et fin tout seul.
- **[HT002](cases/ht002.md)** — l'installer et le faire tourner sur macOS. $38.24 / environ 1 heure, premier run avec goal guard ;
  le programme a bel et bien démarré, et le verdict a pourtant été **non atteint**, remonté à un humain.

Les deux pages écrivent aussi ce qui ne tient pas : dans HT001, l'agent s'est trompé sur un point de sa propre recette,
et HT002 a transformé `git clone && make && ./cppide` en une heure de travail. Chaque chiffre est recalculable depuis `runs/manifest.json`
et `sessions.db` — c'est un enregistrement, pas de la promotion.

## Par où commencer {#从哪读起}

- **Envie de le lancer tout de suite** — [Démarrage rapide](getting-started/quickstart.md) : trois commandes pour démarrer,
  puis comment lire ce qui défile à l'écran.
- **Envie de comprendre les concepts d'abord** — [Concepts fondamentaux](getting-started/concepts.md) : run, step, session, les cinq rôles,
  le tout en cinq minutes.
- **Envie de le brancher sur votre propre code** — [API Python](reference/api.md) : `Runtime`, `Step`, les cinq fabriques de rôles,
  signatures et valeurs par défaut des 62 symboles publics.
