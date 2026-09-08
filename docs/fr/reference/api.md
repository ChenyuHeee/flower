# API Python

Cette page épuise les **62 symboles publics** du `__all__` de premier niveau de `flower` : signatures, paramètres, valeurs par défaut, sémantique, attributs et méthodes publics. Après lecture, vous n'aurez plus besoin d'ouvrir le code source pour retrouver un paramètre.

L'organisation suit **ce qui vous intéresse**, pas les fichiers de modules — pour savoir « comment empêcher le [coordinateur](glossary.md#协调者) de mettre lui-même la main à la pâte », allez à la [couche hook](#hook) ; pour savoir « comment le résultat de l'étape précédente est transmis à la suivante », allez au [workflow](#流程).
La terminologie suit systématiquement le [glossaire](glossary.md).

Version `0.1.0`, dépend de `claude-agent-sdk>=0.2.152`. Toutes les signatures correspondent au code source mot pour mot.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## Ce que contient cette page {#索引}

| Ce qui vous intéresse | Symboles |
|---|---|
| [Lancer un agent](#运行时) | `Runtime` `StepResult` |
| [Enchaîner plusieurs étapes](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Fabriquer un rôle](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Écrire une définition d'agent à la main](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documents structurés](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Intercepter des outils, tailler des résultats, isoler](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Le répertoire de travail du spill](#工作台) | `Workbench` |
| [Comment les sessions sont stockées, et ce qui l'est](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Que faire en cas de coupure réseau](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Remplacer l'UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Reprendre la fois précédente entre processus](#血缘) | `Lineage` |

## Six valeurs par défaut qui mordent {#危险默认值}

Ces six lignes ne sont pas des détails : ce sont les six accidents les plus fréquents. Chacune est expliquée en entier dans la section correspondante.

| Valeur par défaut | Conséquence | Détails |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | Les `Bash`/`Write`/`Edit` du main thread n'ont **aucun hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Impose au spec un `CompactPolicy(mode="no_summary")`, c'est-à-dire `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Une étape avec `resume_from=None` reprend quand même la session précédente entre processus | [Workflow](#workflow) |
| `build_options(fork=True)` sans `resume` | Échoue silencieusement, sans erreur | [build_options](#build-options) |
| `clarify(max_turns=<petit nombre>)` | Transforme « poser des questions sans limite » en formule creuse — chaque question est un tour | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Portée session : interdit aussi aux subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Code source : [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` est le cœur d'exécution. Il détient l'espace de travail, le [session store](glossary.md#会话存储), le [workbench](glossary.md#工作台), la politique de [résilience](glossary.md#韧性) et la politique de [handoff](glossary.md#换代), et n'expose qu'un seul verbe : `run` une étape.
Les nouvelles tentatives, la reprise après interruption, le handoff quand le contexte est plein — tout se fait à l'intérieur de cet unique appel.

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

Les paramètres du constructeur sont **tous keyword-only** (`*` en tête), `workspace` est obligatoire.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | obligatoire | Le `cwd` de l'agent. Résolu à la construction puis `mkdir(parents=True, exist_ok=True)`. Le `project_key` du SDK en est déduit — si le répertoire est déplacé ailleurs, l'ancien `session_id` devient introuvable |
| `run_dir` | `str \| Path` | `"runs"` | Contient `sessions.db`, `manifest.json`, `lineage.json`, ainsi que le workbench par défaut quand `workbench=True`. Également résolu puis mkdir |
| `portable` | `bool` | `True` | Transmis à `build_options(portable=)`, c'est-à-dire `setting_sources=[]` : ne lit ni le `~/.claude/` de la machine hôte ni le `.claude/` du projet. Voir [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Une instance est utilisée telle quelle ; un `bool` donne `TrimPolicy(enabled=bool(trim))`. **Le désactiver empêche seulement de tailler les gros résultats ; le prune continue** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Même règle de conversion. Va de pair avec `coordinator(glance=True)` — si vous laissez le main thread exécuter `git status`, il faut garantir que ce résultat expire |
| `keep_denials` | `int` | `1` | Transmis à `PrunePolicy(keep_denials=)`. Conserve les N derniers appels d'outil refusés ; les plus anciens sont retirés avec leur appel et leur résultat |
| `workbench` | `Workbench \| bool` | `False` | Une instance est utilisée telle quelle ; `True` construit `Workbench(workspace, home=run_dir / "workbench")` (**par défaut hors de l'espace de travail**). Suivi immédiatement d'un `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | À partir de combien de caractères un résultat d'outil est [spillé](glossary.md#落盘). `None` ou `0` = pas de `spill_guard` installé |
| `resilience` | `Resilience \| bool` | `True` | Même règle de conversion |
| `handoff` | `HandoffPolicy \| bool` | `True` | Même règle de conversion |

**Le session store est câblé en dur** : c'est toujours
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Les paramètres du constructeur **n'offrent pas** de point d'entrée pour changer de backend — pour en changer, construisez vous-même un `AgentSpec` + `build_options(session_store=...)`, ou écrasez `rt.store` après construction.

Les deux dernières étapes de la construction sont `load_dotenv()` et `check_credentials()`, **cette dernière lève un `RuntimeError` en cas d'erreur**.
Sans identifiants, l'explosion a lieu à la construction, pas au `run()`.

!!! warning "`workbench=False` + `coordinator()` = aucun mur autour du main thread"
    `delegate_guard` n'est installé que dans `workbench_hooks`, et `workbench_hooks` n'est appelé que si `self.workbench is not None` ; `whitelist_guard`, lui, est sauté par `if not spec.delegate_only`. Or `coordinator()` fixe invariablement `delegate_only=True` et donne par défaut `glance=True` à `Bash`.

    **Conclusion : avec un coordinateur associé à `Runtime(workbench=False)`, ses `Bash`/`Write`/`Edit` ne sont interceptés par aucun hook.**
    Si vous utilisez `coordinator()`, activez le workbench — `Runtime(..., workbench=True)` ou passez une instance de `Workbench`.

!!! warning "`handoff=True` (défaut) désactive de force l'auto-compact"
    Dans `_attempt` : `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, ce qui donne `DISABLE_AUTO_COMPACT=1` dans le sous-processus. La raison : avec les deux mécanismes actifs en même temps, impossible de dire qui est responsable d'une retombée du contexte.

    **Le prix : l'étape qui écrit le handoff doit avoir un chemin dégradé** (`handoff.degraded`), puisqu'il n'y a plus de compact en filet.
    Pour conserver l'auto-compact, fournissez explicitement `AgentSpec.compact` (si le spec le donne lui-même, il est respecté, pas écrasé).

#### Attributs publics {#runtime-属性}

| Attribut | Type | Description |
|---|---|---|
| `workspace` | `Path` | L'espace de travail après résolution |
| `run_dir` | `Path` | Le répertoire de run après résolution |
| `portable` | `bool` | Conservé tel quel |
| `store` | `PruningSessionStore` | Le session store. Pour changer de backend, il faut l'écraser après construction |
| `resilience` | `Resilience` | L'instance normalisée |
| `handoff` | `HandoffPolicy` | L'instance normalisée |
| `workbench` | `Workbench \| None` | `None` quand `workbench=False` |
| `spill_threshold` | `int \| None` | Conservé tel quel, transmis à `workbench_hooks` dans `_attempt` |
| `results` | `list[StepResult]` | Chaque étape exécutée par ce processus, ajoutée dans l'ordre |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Doit être unique par instance** — `manifest.json` déduplique sur le champ `run` ; en cas de collision d'id, le dernier écrivain prend la ligne de l'autre pour la sienne et la supprime |
| `on_session` | `Callable[[str], None] \| None` | Rappelé **immédiatement** à l'obtention d'un nouveau `session_id`, `None` par défaut. **Ne doit couvrir que la ligne `runtime.run`** — le [juge](glossary.md#判定者) utilise le même `Runtime`, et le laisser branché pendant le gate écrirait la session du juge dans la [lignée](glossary.md#血缘) de l'étape de travail |

Constantes de classe : `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`, `INTERRUPT_NOTE` (le paragraphe ajouté après le message humain lors d'une reprise après interruption, expliquant qu'« un appel d'outil en vol renvoyant interrupted est un effet de bord normal de l'interruption, pas une panne d'environnement »).

#### Méthodes publiques {#runtime-方法}

| Méthode | Signature | Description |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Exécute une étape. Voir ci-dessous |
| `interrupt` | `(message: str = "") -> None` | Demande l'interruption du tour en cours. **Appelable depuis n'importe quel thread**. Coopératif : coupure propre à une **frontière de message**, pas d'annulation brutale. Chaîne vide = interrompre sans rien dire |
| `rescue` | `() -> None` | Solde les comptes au mieux avant d'être tué brutalement ; appelé par les gestionnaires `SIGHUP`/`SIGTERM`. L'étape en vol est également écrite dans le manifest, avec `error="killed-by-signal"`. N'effectue que de petites écritures synchrones |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | Dans `str(workspace.resolve())`, tous les `/`, `_`, `.` remplacés par `-`. **Déduit du cwd par le SDK, l'appelant ne peut pas le spécifier** |
| `has_session` | `(session_id: str) -> bool` | Cet id est-il encore retrouvable **sous cet espace de travail** ? Synchrone, ne lit pas le payload |
| `context_of` | `(session_id: str) -> int` | La taille de contexte du dernier tour d'une session, délégué à `store.last_context` |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | obligatoire, positionnel | La déclaration de l'agent à exécuter |
| `prompt` | `str` | obligatoire, positionnel | Ce qui est dit à ce tour |
| `step_name` | `str \| None` | `None` | La clé écrite dans `StepResult.step`, le manifest et la lignée. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Reprend ce `session_id` |
| `fork` | `bool` | `False` | Bifurque vers une nouvelle session sans polluer l'originale. **N'a d'effet que si `resume` est vrai** |
| `resume_at` | `str \| None` | `None` | Reprend à partir d'un message donné (rollback). De même, **n'a d'effet que si `resume` est vrai** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie des événements, voir [`Event`](#event) |

Chaque étape commence par remettre le niveau de contexte à zéro (`self._ctx, self._warned = 0, False`). Suit une boucle avec quatre sorties :

1. **Succès** → sortie de boucle.
2. **Interruption humaine** (`result.error == INTERRUPTED`) → **non soumis à `max_attempts`**, n'attend pas le réseau.
   `resume` la même session avec le message humain, `attempt -= 1` (une interruption ne compte pas comme tentative ratée), prompt = message humain + `INTERRUPT_NOTE`.
   **Sans `session_id` obtenu, il ne reste qu'à s'arrêter.**
3. **Contexte plein** (`result.error == HANDOFF_DUE`, ou bien `handoff.enabled` avec un `session_id` obtenu et `is_overflow(...)` déclenché) → **également non soumis à `max_attempts`**. On vérifie d'abord `len(result.retired) >= handoff.max_generations` ; si dépassé, l'erreur est remplacée par un diagnostic et on sort ; sinon on écrit le [document de handoff](glossary.md#交接书) → `resume=None, fork=False` (**session entièrement neuve**) → le prompt devient `h.prompt_block()` → niveau de contexte remis à zéro → `attempt -= 1`.
4. **Panne réessayable** → sortie si `not resilience.enabled or attempt >= max_attempts` ;
   sortie aussi si `classify(error)` juge qu'il ne faut pas réessayer ; sinon émission d'un `Event("retry")`, `wait_online()` en attente du réseau, `sleep(delay_for(attempt))` ;
   **si un `session_id` a été obtenu, on reprend avec `resume`** (le prompt devient `resilience.resume_prompt`), et `result.resumed` passe à `True`.

Clôture : écriture de `ended_at`, ajout à `self.results`, écriture de `manifest.json`.

`manifest.json` a une sémantique d'**append** : chaque écriture relit le disque et déduplique sur le champ `run` (sa propre ligne est remplacée, celles des autres sont conservées), donc lancer deux flower en parallèle sous le même `run_dir` est sûr — à condition que les `run_id` n'entrent pas en collision.

**Les trois points d'observation du handoff** (tous des `Event("handoff")`, distingués par `payload["phase"]`) :
`near` (approche de `warn_at`, émis une seule fois par génération), `writing` (rédaction du handoff en cours, une dizaine de secondes), `done` (payload avec `degraded` / `path` / `sections`). Le tour qui écrit le handoff est exécuté avec `replace(spec, max_budget_usd=None)` — le handoff doit pouvoir être écrit, il ne peut pas se retrouver bloqué par le budget ;
et avec `on_event=None`, ce tour n'est pas poussé vers l'UI.

Le handoff est écrit dans `<workbench.notes>/交接-<步骤名>.md` ; **sans workbench, rien n'est écrit sur disque**, le document est quand même transmis au successeur via le prompt, il est simplement introuvable après coup. Les anciens handoffs sont déplacés vers `notes/archive/交接/<名>-<时间戳>.md`.

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

L'intégralité des comptes d'une étape terminée.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `step` | `str` | obligatoire | Nom de l'étape (`step_name` ou `spec.name`) |
| `session_id` | `str \| None` | `None` | **Toujours la dernière session ayant pris le relais** — celles brûlées par un handoff en cours de route sont dans `retired` |
| `ok` | `bool` | `False` | L'étape a-t-elle réussi |
| `cost_usd` | `float` | `0.0` | En dollars. **Cumulé** à travers les reprises et les handoffs |
| `num_turns` | `int` | `0` | Nombre de tours, également cumulé |
| `text` | `str` | `""` | **Ne contient que le corps du main thread**. Les propos d'un subagent restent dans son propre transcript, et le task brief qui lui est délégué est de `kind="prompt"` : ni l'un ni l'autre n'y entrent |
| `error` | `str \| None` | `None` | Cause de l'échec. Valeurs spéciales : voir `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Nombre réel de tentatives. Interruptions et handoffs **non comptés** |
| `errors` | `list[str]` | `[]` | Messages d'erreur API synthétiques collectés, **n'entrent pas dans `text`** |
| `resumed` | `bool` | `False` | Y a-t-il eu un resume en cours de route |
| `retired` | `list[str]` | `[]` | Les `session_id` brûlés par les handoffs de cette étape, dans l'ordre |
| `context` | `int` | `0` | La taille de contexte réellement vue par le main thread au dernier tour, soit le critère de handoff |

| Attribut | Type | Description |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, `0.0` si l'étape n'est pas terminée |

---

## Workflow {#流程}

Source : [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Un [workflow](glossary.md#流程) est un ensemble d'[étapes](glossary.md#步骤) enchaînées dans l'ordre,
plus la façon dont l'état circule entre elles et le moment où l'on sort en avance.
**Le framework ne fournit aucun workflow tout prêt ; c'est vous qui l'écrivez** — `starter_flow`
n'est qu'un gabarit qui tourne.

Alias de type `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, présent dans `flower.workflow.__all__`,
absent du `__all__` de premier niveau).

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

La **déclaration** d'une étape. `Step` n'est pas lui-même une fonction — ce qui s'exécute réellement,
c'est `Runtime.run(step.spec, prompt, ...)`. Les trois premiers champs sont positionnels :
`Step("取词", terse, "读 seed.txt …")` est une écriture valide.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom de l'étape. **Clé stable entre processus** — elle atterrit dans `ctx[name]`, `ctx["_results"]`, le manifest et le lineage. Renommer = couper le lineage |
| `spec` | `AgentSpec` | requis | Quel agent exécuter |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | Ce qu'on lui dit. Peut être une closure qui calcule à partir de `ctx` |
| `resume_from` | `str \| None` | `None` | La session de quelle étape reprendre. Si l'étape visée n'a produit aucune session, **lève `ValueError`** — pas de saut silencieux |
| `fork` | `bool` | `False` | Fork à partir de `resume_from`. **Sans `resume_from`, sans effet** |
| `retries` | `int` | `0` | Combien de tentatives supplémentaires quand le gate ne passe pas. `retries=0` = un seul tour |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Décide si cette tentative passe. **Peut être async**. Renvoyer `False` vaut échec. **Appelé une seule fois par tentative** — il peut avoir des effets de bord (écrire le brief sur disque, par exemple) et ne doit pas être déclenché deux fois |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, voir plus bas |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Renvoyer `False` **saute l'étape entière** : aucun result produit, rien dans `ctx["_results"]`. **Peut être async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Ce qu'on dit **au tour suivant** quand le gate ne passe pas. **Peut être async**. Le fournir change la sémantique des retries, voir plus bas |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Le prompt utilisé en continuité (au lieu de repartir de zéro) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Décide de ce qui va dans `ctx[name]`. Par défaut le texte brut de `result.text`. **Doit être une fonction synchrone** |

| Méthode | Signature | Description |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Si `resuming` et qu'un `resume_prompt` existe, c'est lui ; sinon `prompt` ; si c'est un appelable, on l'appelle avec `ctx` |

**Trois façons de raccorder les sessions** (au sein d'un même run) :

| Écriture | Effet |
|---|---|
| `resume_from=None` (défaut) | Session neuve, avec pour seul contexte ce que le prompt transmet. Bon marché, isolé. **Mais avec `Workflow(continuous=True)`, la session de l'étape de même nom est reprise du lineage inter-processus** |
| `resume_from="上一步名"` | Reprise de la même session, contexte complet. Cher, cohérent |
| `resume_from="上一步名", fork=True` | Fork, sans polluer la session d'origine. Pour la revue ou plusieurs pistes en parallèle |

**`on_reject` change la sémantique des retries** :

- Absent → la tentative suivante **repart de zéro** (même prompt, même `resume_from`).
- Présent → la tentative suivante **reprend la session qui vient d'être refusée**, le prompt est remplacé par sa valeur de retour, `fork` est forcé à `False`.
- Renvoie une chaîne vide → pas de renvoi, on retombe sur un départ de zéro.
- `result.session_id` vaut `None` → on retombe aussi sur un départ de zéro.

**Les trois valeurs de `on_fail`** :

| Valeur | Comportement |
|---|---|
| `"stop"` (défaut) | Écrit `ctx["_failed_at"] = name` et **interrompt tout le workflow** |
| `"skip"` | Passe à l'étape suivante, **`ctx[name]` n'est pas écrit** — un `lambda ctx: ctx["某步"]` en aval lèvera `KeyError` |
| `"continue"` | `ctx[name] = result.text`, on continue avec un résultat incomplet |

Que ce soit passé ou non, `ctx["_results"][name] = result` est toujours écrit ; si `result.session_id`
est non vide, il est aussi écrit dans `ctx["_sessions"]` avec `lineage.remember(...)`.

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

Exécute une suite de `Step` dans l'ordre et renvoie le `ctx` final. `steps` est positionnel,
`Workflow([...])` est valide.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `steps` | `list[Step]` | requis | Exécutées dans l'ordre |
| `name` | `str` | `"workflow"` | Nom du workflow |
| `context` | `Ctx` | `{}` | Dictionnaire de contexte initial. **Au deuxième run du même `Workflow`, c'est le même dict** |
| `channel` | `HumanChannel \| None` | `None` | À accrocher ici quand il faut s'arrêter pour demander à un humain. `run()` branche automatiquement son `on_event` sur la même sortie, **uniquement si `channel.on_event is None`** ; c'est aussi par ce champ que le programme pilote sait à qui répondre |
| `workbench` | `Workbench \| None` | `None` | Le workbench désigné par le workflow, pour que le programme pilote le trouve |
| `continuous` | `bool` | `True` | Même chemin = même conversation. Implémenté par [`Lineage`](#lineage) |

| Paramètre de `run()` | Type | Défaut | Description |
|---|---|---|---|
| `runtime` | `Runtime` | requis, positionnel | Avec quel runtime exécuter |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie d'événements, transmise telle quelle à chaque `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Rappelée une fois après chaque étape |

!!! warning "`continuous=True` est la valeur par défaut, `resume_from=None` ne veut pas dire session neuve"
    Avec la continuité activée, `run()` appelle d'abord `Lineage.open(run_dir, workspace)`, puis vérifie
    chaque enregistrement un par un avec `runtime.has_session(sid)` pour voir s'il est toujours en base ;
    seuls les vivants sont versés dans `ctx["_sessions"]`. Résultat :
    **même une étape avec `resume_from=None` continue de parler dans la session de la dernière fois** —
    y compris après un processus tué ou un redémarrage de la machine.

    Pour avoir une session neuve à chaque fois, écrivez explicitement `Workflow(..., continuous=False)`.
    Par ailleurs : **le nom d'étape est une clé stable entre processus ; le changer revient à couper le lineage.**

Les **clés privées** que `run()` écrit dans le ctx (toutes préfixées par `_`, aucune collision possible avec un nom d'étape) :

| Clé | Contenu |
|---|---|
| `_runtime` | Le `Runtime` passé en argument. **C'est par lui qu'un gate lance un agent** |
| `_on_event` | La sortie d'événements. L'agent lancé dans un gate doit lui aussi pouvoir atteindre l'UI, sinon l'écran reste noir |
| `_sessions` | `dict[步骤名, session_id]`, lu avec `setdefault` |
| `_results` | `dict[步骤名, StepResult]` |
| `_lineage` | L'objet `Lineage`. Présent uniquement si `continuous=True` et que le runtime a un `run_dir` + un `workspace` |
| `_woke` | Valeur de retour de `lineage.bump()` : le numéro de ce réveil |
| `_aborted` | Le message du `StepAbort` |
| `_failed_at` | Le nom de l'étape en échec quand `on_fail="stop"` |

Payload de `Event("step")` : `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Étiquettes de retry** : la tentative 0 utilise `step.name` ; ensuite, avec `on_reject`, `f"{name}#round{attempt+1}"`,
sinon `f"{name}#retry{attempt}"`. Dans le manifest, on voit d'un coup d'œil comment l'étape s'est terminée.
**Les noms suffixés n'entrent pas dans le lineage inter-processus** — `Lineage.remember` utilise le nom d'origine.

`runtime.on_session` ne couvre que la ligne `runtime.run`, avec un `try/finally` qui garantit son retrait avant le gate.
`prompt_cur` / `resume_cur` / `fork_cur` sont des variables locales, jamais réécrites dans `step` — le même objet `Step`
peut être exécuté une seconde fois.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Levée par un `gate` = **arrêt immédiat, pas de nouvelle tentative**. Différence avec « renvoyer `False` » :
`False` veut dire « pas cette fois, on refait un tour » ; `StepAbort` veut dire « refaire n'y changera rien ».

Après la levée : `ctx["_aborted"] = str(exc)`, `passed = False`, **sortie de la boucle de retry
(les `retries` restants ne sont pas consommés)**, puis traitement comme un échec ordinaire via `on_fail`
(par défaut `"stop"`).

`with_goal` la lève à deux endroits : quand `ctx["_runtime"]` est introuvable, et quand le verdict est
`unreachable` sans personne pour répondre.

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

Produit un `Step` de [clarification préalable](glossary.md#前置确认) : cerner le besoin → parser en
[`Brief`](#brief) → geler et écrire sur disque dès que les quatre sections sont complètes.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Le canal de questions |
| `brief_path` | `str \| Path` | requis | Où atterrit le [brief](glossary.md#需求确认书). **Doit atterrir dans le workbench dont l'index est réellement injecté** |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | La demande brute de l'humain |
| `name` | `str` | `"确认需求"` | Nom de l'étape, et en même temps clé dans le `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Si absent : `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions supplémentaires ajoutées au [clarificateur](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = redemander à chaque fois, que le brief existe ou non |
| `on_fail` | `str` | `"stop"` | Comme `Step.on_fail` |
| `retries` | `int` | `0` | Combien de fois redemander si les quatre sections ne sont pas réunies |
| `**spec_kw` | | | Transmis tel quel à [`clarify()`](#clarify-role), on peut donc écrire `can_read=False`, `max_budget_usd=...` |

Les champs du `Step` produit sont remplis ainsi :

- `resume_prompt = CLARIFY_RESUME`.
- `when` : `always_ask=True` → toujours `True` ; sinon, si `Brief.load(brief_path)` est complet, il est versé
  dans le ctx **puis on renvoie `False` (saut)** — même en sautant il faut le verser, sinon l'aval n'a pas le besoin.
- `gate` : `Brief.parse(result.text)` ; incomplet → écrit `ctx[MISSING_KEY]` et renvoie `False` ;
  complet → `b.write(brief_path)` pour geler, versement dans le ctx, renvoie `True`.
- `reduce` : renvoie `ctx[BRIEF_KEY].prompt_block()`, **pas le texte brut du modèle** — le texte brut peut charrier ce qu'il a écrit en plus.
- `resume_from` **reste à `None`** par défaut : l'étape suivante est une session neuve, elle ne reçoit que le brief, pas le questionnaire.
  Les questions-réponses de la clarification préalable **ne sont jamais entrées** dans le contexte du coordinateur ; elles n'y sont pas entrées puis élaguées.

Les trois versements dans le ctx : `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Constante | Valeur | Description |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` est l'objet `Brief` ; `ctx[step.name]` est son `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Quelles sections manquent quand la clarification échoue (noms de sections en chinois), pour affichage dans l'UI |
| `CLARIFY_RESUME` | un prompt en chinois | « Reprends la clarification du besoin restée inachevée — **ce n'est pas un nouveau départ**… ». Sans cette phrase, la continuité renverrait la demande initiale comme une tâche neuve et le clarificateur pourrait reposer des questions déjà posées |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

Produit un `Step` qui **fixe l'objectif** : le [juge](glossary.md#判定者) lit le brief, rédige l'objectif +
la checklist de verdict, le tout parsé en [`Goal`](#goal) puis gelé et écrit sur disque. Même forme que `clarify_step`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Le canal de questions |
| `goal_path` | `str \| Path` | requis | Où atterrit le fichier objectif |
| `brief_key` | `str` | `"确认需求"` | Le texte du brief est pris dans `ctx[brief_key]` et inséré dans le prompt. **S'il est introuvable, c'est `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nom de l'étape |
| `spec` | `AgentSpec \| None` | `None` | Si absent : `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions supplémentaires |
| `always_set` | `bool` | `False` | `True` = recalculer la checklist, que le fichier objectif existe ou non |
| `on_fail` | `str` | `"stop"` | Idem ci-dessus |
| `retries` | `int` | `0` | Idem ci-dessus |
| `**spec_kw` | | | Transmis à [`judge()`](#judge-role) |

**Il n'y a pas de paramètre `can_run`** — pour que le juge qui fixe l'objectif puisse lancer des commandes,
il faut passer `can_run=True` via `**spec_kw`. Sans cela, il n'a pas `Bash` et la règle de `JUDGE_RULES`
« commence par regarder dans quel environnement tu es » n'est pas exécutable.

Au-delà du parsing et du gel, le `gate` fait une chose de plus : si l'objectif contient des entrées
`[此环境无法验证:…]`, il émet **sur-le-champ**, via `ctx["_on_event"]`, un
`Event("task", payload={"unverifiable", "total", "path"})` en guise d'alerte — le sort de ces entrées est
scellé au moment où l'on fixe l'objectif ; attendre le verdict, c'est avoir déjà dépensé le prix d'un tour de travail complet.

**Aucun `resume_prompt` n'est défini** — fixer l'objectif doit de toute façon renvoyer le brief en entier.

| Constante | Valeur | Description |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` est l'objet `Goal` ; `ctx[step.name]` est le markdown |
| `VERDICT_KEY` | `"_verdict"` | Le dernier [`Verdict`](#verdict) en date, pour l'UI |
| `ROUND_KEY` | `"_goal_rounds"` | Nombre de tours de verdict effectués |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

Pose un [gardien d'objectif](glossary.md#目标看守) sur un `Step` existant : à la fin de chaque tour, le juge
rend un verdict indépendant ; si l'objectif n'est pas atteint, le travail est renvoyé pour être poursuivi.

Le résultat est `replace(step, retries=max(0, rounds - 1), gate=<新 gate>, on_reject=<新 on_reject>)` —
on utilise `dataclasses.replace` plutôt qu'une reconstruction champ par champ ; une reconstruction a déjà
oublié `resume_prompt` une fois, **sans lever la moindre erreur**, avec pour seul effet de renvoyer
l'intégralité du brief à chaque reprise.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `step` | `Step` | requis, positionnel | L'étape gardée |
| `channel` | `HumanChannel` | requis, positionnel | Le canal pour appeler l'humain quand le verdict est bloqué |
| `goal_path` | `str \| Path` | requis | Le fichier objectif, lu ici quand `ctx[GOAL_KEY]` est incomplet |
| `spec` | `AgentSpec \| None` | `None` | Si absent : `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Nombre total de tours, pas de tours supplémentaires** : `rounds=3` → `retries=2` → trois tours de travail au maximum. `rounds=1` = un tour, un verdict, échec si le verdict ne passe pas |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le juge |
| `can_run` | `bool` | `False` | Le juge peut-il lancer `Bash` |
| `name` | `str \| None` | `None` | Nom du juge, par défaut `f"{step.name}·判定"` |
| `**spec_kw` | | | Transmis à `judge()` |

Le `gate` est **async**, déroulé :

1. `ctx["_runtime"]` absent → **lève `StepAbort`** (« 拿不到 Runtime,无法判定目标 »). **Ne pas faire semblant que ça passe.**
2. `ctx[ROUND_KEY] += 1`.
3. Récupération de l'objectif : en priorité un `Goal` complet dans `ctx[GOAL_KEY]`, sinon `Goal.load(goal_path)`, sinon un `Goal()` vide.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Le juge est un `Runtime.run` indépendant, `resume` vaut toujours `None` — c'est toujours une session neuve** ;
   `step_name` porte le numéro de tour, il n'entre donc pas dans le lineage inter-processus.
5. `Verdict.parse(vr.text)` est écrit dans `ctx[VERDICT_KEY]`.
6. `v.achieved` → renvoie `True`.
7. Pas `unreachable` (y compris les cas ambigus avec `v.ok=False`) → en cas d'ambiguïté, on ajoute une reason par défaut et on renvoie `False`.
   **Toute ambiguïté compte comme non atteint** — on ne laisse pas un « ça a l'air bon » clore le travail.
8. `unreachable` → `await channel.ask(...)` pour interroger l'humain, trois options :
   - Personne ne répond (`a.state != "answered"`) → **lève `StepAbort`**. Continuer à tourner à vide est le choix le plus cher.
   - « Accepter ce résultat et continuer ainsi » → renvoie `True`.
   - « Modifier l'objectif » → nouvelle question pour le nouvel objectif, `g.amend(...).write(goal_path)`, mise à jour de `ctx[GOAL_KEY]`, renvoie `False`.
   - Le reste (y compris une réponse libre tapée par l'humain) → traité comme « tu t'es trompé dans ton verdict », le propos de l'humain est consigné dans `v.reason`, renvoie `False`.

`on_reject` est **synchrone** : il renvoie `ctx[VERDICT_KEY].feedback()`, ou `""` s'il n'y a pas de `Verdict`
(on retombe alors sur un départ de zéro).

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

Assemble un workflow en trois étapes qui tourne tel quel : **clarifier le besoin → fixer l'objectif → travailler**
(avec gardien d'objectif). C'est ce qu'utilise la commande `flower`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `ask` | `str` | requis, positionnel | Une demande en une phrase. **Au réveil, ce n'est pas une nouvelle tâche, c'est « une phrase de plus »** |
| `workspace` | `str \| Path` | `"."` | L'espace de travail |
| `run_dir` | `str \| Path` | `"runs"` | Le répertoire de run |
| `new` | `bool` | `False` | `True` = archiver le lineage + le brief + l'objectif (les trois ensemble) et repartir de zéro |
| `isolate` | `bool` | `False` | Ouvre une [isolation](glossary.md#隔离) par worktree pour l'exécutant. Le workbench se déplace alors vers `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Renvoie seulement le Workflow contenant l'étape de clarification |
| `goal` | `bool` | `True` | Poser ou non le [gardien d'objectif](glossary.md#目标看守). `False` = l'étape de travail terminée, c'est fini |
| `rounds` | `int` | `3` | Transmis à `with_goal(rounds=)`, nombre total de tours |
| `judge_can_run` | `bool` | `False` | Transmis à `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Transmis à `HumanChannel`, `None` = sans limite |
| `timeout_s` | `float \| None` | `1800.0` | Transmis à `HumanChannel`. `0` = tout automatique, toute question tombe immédiatement dans le vide |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le clarificateur |
| `worker_prompt` | `str` | voir la signature | Le system prompt de l'exécutant |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier du brief, déposé dans `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier objectif, idem |
| `log_name` | `str` | `"问答记录.md"` | Nom du fichier de journal des questions-réponses, idem |

Assemblage fixe :

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Branches de comportement :

- `isolate=True` et workspace qui n'est pas un dépôt git → **lève `ValueError`**, sans attendre que l'outil `Agent`
  remonte l'erreur (à ce moment-là l'argent est déjà dépensé).
- **Détection du réveil** : si `Brief.load(brief_path)` existe et que `complete()` est vrai, c'est un réveil.
  Pas un réveil et `ask` vide → **lève `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Au réveil, cette phrase atterrit simultanément à **trois endroits** ; s'il en manque un, elle échoue silencieusement :
  ajoutée au brief (`ch.amend(said, label="唤醒时追加")`, sans réécriture si elle est déjà dans le fichier),
  transmise à `goal_step(always_set=True)` pour recalculer la checklist (sinon le juge lit toujours l'ancien objectif),
  et remise directement au coordinateur (son contexte contient l'**ancien** objectif ; sans elle, il travaille selon
  les anciens critères puis se fait juger selon les nouveaux).

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**Une sonde en lecture seule avant le départ, pas un octet écrit.** Sert à dire à l'humain, avant que ça démarre
vraiment, s'il s'agit d'une reprise ou d'un départ de zéro.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | L'espace de travail, positionnel |
| `run_dir` | `str \| Path` | `"runs"` | Le répertoire de run |
| `isolate` | `bool` | `False` | Détermine l'emplacement du workbench, doit valoir la même chose que dans `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier du brief |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier objectif |

Le dict renvoyé :

| Clé | Type | Description |
|---|---|---|
| `waking` | `bool` | Le brief existe et ses quatre sections sont complètes |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Nombre d'entrées de la checklist d'objectif, `0` s'il n'y a pas d'objectif |
| `woke` | `int` | `Lineage.woke`, combien de réveils ont déjà eu lieu |
| `steps` | `dict` | Copie de `Lineage.steps`, nom d'étape → `session_id` |

L'emplacement du workbench n'est **défini qu'ici et dans `starter_flow`** : `isolate=True` → `<ws>.parent/.flower-<ws.name>`
(hors du dépôt) ; sinon `<ws>/.flower`. Un programme pilote qui veut savoir où est le brief passe aussi par cette
fonction — reconstruire le chemin à la main ne lève aucune erreur, ça échoue simplement en silence.

---

## Fabriques de rôles {#角色工厂}

Source : [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Les cinq rôles sont tous des fonctions fabriques. Chaque rôle = **un texte de règles injecté + un jeu d'outils + un jeu de hooks**.
`worker()` produit un `AgentDefinition` du SDK (destiné à un subagent) ; les quatre autres produisent un [`AgentSpec`](#agentspec)
(qui ouvre sa propre session).

Les rôles eux-mêmes **n'attachent aucun hook** — l'interception des outils est montée automatiquement par
`Runtime._attempt` selon `spec.delegate_only`, voir la [couche hook](#hook).

Constantes internes de groupes d'outils (non exportées, mais elles décident des valeurs par défaut) :

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

Fabrique le [coordinateur](glossary.md#协调者) qui vit sur le [thread principal](glossary.md#主线程) : il découpe la tâche, distribue le travail, lit les rapports, décide,
**mais ne met pas la main à la pâte**. Les trois premiers paramètres sont positionnels.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | obligatoire | Nom du rôle, et aussi nom d'étape par défaut |
| `instructions` | `str` | obligatoire | Instructions métier. Au final : `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obligatoire | Les rôles dont il dispose, versés dans `AgentSpec.agents`. **Leurs outils web en lecture seule sont en plus fusionnés dans le `allowed_tools` du coordinateur lui-même**, voir ci-dessous |
| `channel` | `HumanChannel \| None` | `None` | Si fourni, ajoute les deux outils `inbox` **et** `ask`, et renseigne `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]` ; `False` → sans `Read` |
| `glance` | `bool` | `True` | Ajoute `"Bash"` et renseigne `AgentSpec.glance`. **Ce qui peut réellement tourner est filtré par `delegate_guard`**, pas ici |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Mode de permission. **Attention à cette valeur par défaut** — la passer à `clarify()`/`judge()` démonte la protection de ces deux rôles |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, ne sera pas forcé en `no_summary` par `Runtime` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks supplémentaires, fusionnés avec `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variables d'environnement supplémentaires |

Trois éléments sont figés dans l'`AgentSpec` produit : `delegate_only=True`, `agents=workers`, et
`workbench` garde la valeur par défaut `True` d'`AgentSpec`.

#### Les outils web des `workers` sont fusionnés ici {#coordinator-web-merge}

Une fois la liste constituée, `coordinator()` parcourt les `AgentDefinition.tools` de chacun ; tout ce qui tombe
dans `WEB_TOOLS` (`WebFetch`, `WebSearch`, `roles.py:33`) est également ajouté à l'`allowed_tools` du coordinateur
lui-même (`roles.py:523-526`).

**Raison : `allowed_tools`, tout comme `disallowed_tools`, est au niveau session.** C'est la preuve la plus dure
de tout le document sur ce point — cela ne concerne pas que le thread principal. Un outil absent de cette liste
au niveau session passe aussi par l'approbation de permission quand c'est un **subagent** qui l'appelle ;
en mode sans surveillance, personne n'approuve, le harness répond
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`), et le modèle réessaie indéfiniment le même appel. Vécu en vrai : on avait ajouté
`WebFetch`/`WebSearch` à l'exécutant, mais uniquement dans `AgentDefinition.tools` ; ce run novel a produit plus de
vingt user-rejected et pas un seul mot écrit (`roles.py:513-518`).

Les deux champs ont la même nature au niveau session, mais **les symptômes diffèrent** : `disallowed_tools` échoue
sur-le-champ, `allowed_tools` réessaie en silence jusqu'à la mort. Le second est plus difficile à diagnostiquer,
parce que rien à l'écran ne ressemble à une erreur.

**On ne fusionne que ce qui est en lecture seule et sans effet de bord.** `Write`/`Edit`/`Bash` sont
**délibérément exclus** : dès que le thread principal en est dispensé d'approbation, le mur « le coordinateur ne
met pas la main à la pâte » de `delegate_guard` n'a plus de sens ; et de toute façon les `Bash`/`Write` des
subagents passent déjà (462 autorisations mesurées, `roles.py:520-522`).

Le code source écrit noir sur blanc **de ne pas utiliser `disallowed_tools` pour obtenir « coordonner sans agir »** —
c'est au niveau session, cela interdirait aussi les `Bash`/`Write` des subagents, voir l'avertissement de
[`AgentSpec`](#agentspec). La bonne méthode est celle d'ici : `delegate_only=True` + ne rien mettre dans
`allowed_tools`, puis laisser [`delegate_guard`](#delegate-guard) n'intercepter que le thread principal via `agent_id`.

Si `channel` est fourni, **les deux outils arrivent ensemble**, ce n'est pas optionnel : dès que le serveur MCP est
monté, les deux sont là, et `allowed_tools` n'étant pas exclusif, ils sont appelables qu'ils y figurent ou non.
Sans surveillance, chaque `ask` va bloquer jusqu'au bout de `timeout_s` — dans ce cas, utiliser
`HumanChannel(timeout_s=0)`.

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

Fabrique la définition du [subagent](glossary.md#subagent) qui fait réellement le travail. Les deux premiers
paramètres sont positionnels. Retourne un `AgentDefinition` du SDK, à passer directement dans
`coordinator(workers={...})`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `description` | `str` | obligatoire | **Ce sur quoi le coordinateur se base pour choisir** — écrire clairement « quel travail lui confier » |
| `prompt` | `str` | obligatoire | Son system prompt. Avec `discipline=True`, assemblé en `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | L'exécutant ne doit pas être rétrogradé |
| `effort` | `str \| int \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Devient le **`maxTurns`** du SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Devient le **`permissionMode`** du SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Quels skills il a le droit d'utiliser |
| `discipline` | `bool` | `True` | Concaténer ou non le bloc de discipline de compte rendu `WORKER_RULES` |
| `isolate` | `bool` | `False` | Pose la marque d'[isolation](glossary.md#隔离), passe par `isolated()`, **ce n'est pas un champ de `AgentDefinition`** |

`isolate=True` exige que le workspace soit un dépôt git, sinon l'outil `Agent` renvoie directement
`"not in a git repository"` — **il n'y a pas de dégradation silencieuse**. Et comme la marque est un attribut
Python, un `dataclasses.replace()` sur l'`AgentDefinition` la perd : l'isolation devient silencieusement inopérante.

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Fabrique le [clarificateur](glossary.md#确认者) : il tire le besoin au clair avant d'agir, ne fait rien, ne fait que
poser des questions, et sort à la fin exactement quatre sections.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | obligatoire | Nom du rôle, positionnel |
| `channel` | `HumanChannel` | obligatoire | Canal de questions, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Si `True`, ajoute `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | **Pas de plafond de tours** |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produit : `allowed_tools = [channel.tool_name] + (les cinq outils si lecture autorisée)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (il n'a pas d'outil d'écriture, l'index n'a aucun sens
pour lui), `permission_mode` hérite du `"default"` par défaut d'`AgentSpec`.
**Pas de `Write` / `Edit` / `Bash` / `Agent`, ni d'`inbox`** (contrairement au coordinateur).

!!! warning "Mettre un petit `max_turns` rend creuse la promesse de questions illimitées"
    Chaque question consomme un tour. `max_turns=16` signifie « une dizaine de questions au maximum » ; la phrase
    « pas de plafond de tours » du canal devient caduque sur-le-champ.

    Pour ouvrir vraiment les questions, il faut ouvrir **les deux** : `HumanChannel.max_asks` (déjà `None` =
    illimité par défaut) et `max_turns` (déjà `None` par défaut).

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Fabrique le [juge](glossary.md#判定者) : soit il fixe l'objectif avant le départ, soit il rend le verdict du tour
à la fin de chaque tour.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | obligatoire | Nom du rôle, positionnel |
| `channel` | `HumanChannel` | obligatoire | Canal de questions, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Si `True`, ajoute `Bash` à la whitelist ; `whitelist_guard` laisse alors passer `Bash` mais bloque toujours `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produit : `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (si `can_run`) `["Bash"]`,
`workbench=False`, le reste comme `clarify()`. **Pas de `Write` / `Edit` / `Agent`, ni d'`inbox`.**

**Arbitrage** : `can_run=True` donne un verdict plus dur (il peut vraiment exécuter les commandes de recette),
au prix de la capacité du juge à modifier l'espace de travail — `Bash` sait écrire des fichiers. Pour un verdict
absolument neutre, ne pas l'activer.

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

Fabrique l'[oracle](glossary.md#旁路顾问) : pendant que le run tourne encore, on lui demande « où en est-on ? »,
il jette un œil aux événements récents et au workbench puis répond. **Ce qu'il dit n'entre pas dans le contexte
de ce run.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nom du rôle, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | **`12`** | Frein par défaut |
| `max_budget_usd` | `float \| None` | **`0.5`** | Frein par défaut. C'est « une question en passant », ça ne doit pas déraper |

L'`AgentSpec` produit : `allowed_tools = ["Read", "Glob", "Grep"]` (**pas de channel** — il ne pose pas de
questions, il y répond), `workbench=True` (**le seul des cinq rôles à ouvrir le workbench sans être coordinateur** —
c'est justement pour aller lire les livrables et les notes).

### Les cinq textes de règles {#rules}

Les cinq constantes sont dans `__all__` : on peut les `import` telles quelles pour les lire, les concaténer, les modifier.

| Constante | Injectée dans | Mode d'injection | Points clés |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Tu es « quelqu'un qui sait se servir de Claude Code », pas un exécutant ; interdit d'écrire des fichiers / modifier du code / lancer des tests ; `Bash` sert juste à « jeter un œil » et le résultat périmera ; **le [brief de tâche](glossary.md#任务书) ne contient que ce qui est propre à cette tâche** ; la seule règle qu'il reste à transmettre est « où est le workbench + les longues sorties vont dans `artifacts/` + ne renvoyer que des chemins » ; consulter `inbox` après chaque action d'étape terminée ; `ask` bloque, ne l'utiliser qu'aux vraies bifurcations |
| `WORKER_RULES` | `worker()` | Concaténé **après** le `prompt` du subagent | Format de réponse **Conclusion / Justification / Livrables / Non vérifié**, pas plus de 30 lignes ; interdit de coller le contenu des fichiers, les sorties de commandes, les logs, les diffs bruts ; interdit de raconter les essais-erreurs ; regarder `.flower/scripts/` avant d'agir. **Volontairement, il n'y est pas écrit « les longues sorties vont dans `artifacts/` »** — le chemin réel est généré par `Workbench`, l'écrire en dur serait faux |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Ne fait rien, se contente de tirer le besoin au clair ; **aucune limite de nombre, on questionne jusqu'à ce que ce soit clair** ; l'humain peut être absent, en cas de timeout juger soi-même et l'écrire dans 「未知与假设」 ; sortie de **exactement quatre sections** ; ne pas écrire de code, ne pas coller le contenu des fichiers |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Deux missions, l'une ou l'autre. **Fixer l'objectif** : chaque item de la liste doit être vérifiable sur-le-champ, la longueur de la liste est dictée par le nombre de façons d'échouer, **les limites ne sont pas des items de verdict**, un item non vérifiable se termine par `[此环境无法验证:原因]`. **Juger le tour** : sortie de **exactement trois sections**, on juge **les livrables, pas le code source**, par défaut on ne croit pas « c'est fait », « pas atteint » et « invérifiable ici » sont deux conclusions différentes, la seconde **n'autorise absolument pas un verdict de réussite** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Une voie de dérivation ; ce run tourne encore, tu ne l'interromps pas et tu n'y participes pas ; **lecture seule** ; jetable après réponse, ce que tu dis n'entrera pas dans le contexte de ce run ; tu n'as en main que « la fenêtre des événements récents » et « le workbench » ; regarder avant de répondre, dire qu'on ne peut pas répondre si c'est le cas, être bref |

---

## Définition d'agent {#agent-定义}

Source : [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` est la déclaration complète d'un agent spécialisé ; `build_options` la compile en `ClaudeAgentOptions`
du SDK. C'est un `AgentSpec` que produisent les [fabriques de rôles](#角色工厂) — pour une composition hors fabrique,
on le construit directement.

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | obligatoire | Nom du rôle. Sert aussi de `step_name` par défaut à `Runtime.run`, et de nom propre dans le texte de refus de `whitelist_guard` |
| `instructions` | `str` | obligatoire | Instructions métier. **[Ajouté](glossary.md#叠加) à la suite du system prompt natif de Claude Code, ce n'est pas un remplacement** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Liste de dispense d'approbation, pas une whitelist exclusive** — le modèle peut toujours appeler des outils qui n'y figurent pas. L'exclusivité passe par [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Au niveau session**. Voir l'avertissement ci-dessous |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Mode de permission |
| `agents` | `dict[str, Any] \| None` | `None` | Table des définitions de subagents, les valeurs sont des `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Table des serveurs MCP. `HumanChannel.mcp_servers()` se branche ici directement |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks supplémentaires, `Runtime` les fusionne avec les siens via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, ne sera pas forcé en `no_summary` par `Runtime` |
| `env` | `dict[str, str]` | `{}` | Variables d'environnement injectées dans le sous-processus. `compact.env()` vient les compléter par `update` |
| `glance` | `bool` | `False` | Autorise le coordinateur à lancer lui-même un `Bash` « juste pour jeter un œil ». Ce qui passe est décidé par [`is_ephemeral`](#is-ephemeral), et le résultat sera marqué périmé par `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Injecter ou non l'index du workbench dans le system prompt de cet agent. **À désactiver pour un rôle sans outil d'écriture** (`clarify()` / `judge()` sont déjà à `False` par défaut) |
| `delegate_only` | `bool` | `False` | Coordonner sans agir. Si `True`, `Runtime` monte `delegate_guard` et **ne monte pas** `whitelist_guard` |

!!! warning "`disallowed_tools` est au niveau session et interdit aussi les subagents"
    Message d'erreur constaté : `"Bash is disabled for this session, in subagents as well as here"`.
    Autrement dit, si l'on utilise `disallowed_tools=["Bash"]` pour empêcher le coordinateur d'agir, les exécutants
    délégués ne peuvent plus lancer de commandes non plus — tout le run est fichu.

    Pour « coordonner sans agir », utiliser `delegate_only=True` + ne rien mettre dans `allowed_tools`, et laisser
    [`delegate_guard`](#delegate-guard) n'intercepter que le thread principal via `agent_id`.

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

Compile un `AgentSpec` en `ClaudeAgentOptions` du SDK. C'est ce qu'appelle `Runtime._attempt` en interne ;
c'est aussi le point d'entrée si l'on pilote le SDK soi-même (sans `Runtime`).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | obligatoire, positionnel | La déclaration à compiler |
| `cwd` | `str \| Path \| None` | `None` | `cwd` n'est écrit que si non `None` |
| `session_store` | `SessionStore \| None` | `None` | `session_store` et `session_store_flush` ne sont écrits que si non `None` |
| `resume` | `str \| None` | `None` | Quelle session reprendre |
| `fork` | `bool` | `False` | Devient `fork_session`. **Imbriqué dans `if resume:`** |
| `resume_at` | `str \| None` | `None` | Devient `resume_session_at`. **Également imbriqué dans `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` et `PLUGIN_DIR` existe → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]` ; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Répertoires autorisés en plus. **Obligatoire si le workbench est hors de l'espace de travail** |
| `flush` | `str` | `"eager"` | Devient `session_store_flush` |
| `prelude` | `str` | `""` | Bloc ajouté après `instructions` (c'est par là que passe l'index du workbench) |

Correspondances :

| Clé d'option produite | Valeur |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Repris tels quels de `spec` |
| `setting_sources` | `[]` (portable) ou `["project"]` |
| `plugins` | Présent seulement si le répertoire `plugin/` à la racine du dépôt existe |
| `cwd` / `add_dirs` | Écrits seulement si non vides |
| `session_store` / `session_store_flush` | Écrits seulement si `session_store` n'est pas `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Chacun écrit seulement s'il est non vide |
| `env` | `dict(spec.env)` puis `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **N'ont effet que si `resume` est vrai** |

`PLUGIN_DIR` est le répertoire `plugin/` à la racine du dépôt (trois niveaux au-dessus de `flower/core/agent.py`).
Après une installation pip, ce répertoire n'existe pas forcément ; le code le teste avec `is_dir()`.

!!! warning "`fork=True` sans `resume` est silencieusement sans effet"
    `fork_session` et `resume_session_at` sont tous deux imbriqués dans `if resume:` — sans `resume`, ils n'ont
    strictement aucun effet, **et aucune erreur n'est levée**. De même, `Runtime.run(resume_at=...)` ne fonctionne
    que si `resume` est fourni, et **`Workflow` ne passe jamais `resume_at`** : pour revenir en arrière au message
    près, il faut appeler `Runtime.run` directement.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Le tableau de bord de l'auto-[compact](glossary.md#压缩) ; son produit est un jeu de variables d'environnement à
injecter dans le sous-processus. L'algorithme de compact lui-même est dans le binaire du harness et n'est pas
modifiable ; la seule chose modifiable est « déclencher ou non ».

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = ne rien régler, seuil = fenêtre − 33k ; `"no_summary"` → `DISABLE_AUTO_COMPACT=1` ; `"off"` → `DISABLE_COMPACT=1` (désactive aussi `/compact`). **Toute autre valeur lève `ValueError`**, il n'y a pas d'ignorance silencieuse |
| `window` | `int \| None` | `None` | Non `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Côté CLI, la borne est 100k–1M ; une valeur inférieure à 100k est remontée à 100k |

| Méthode | Signature | Description |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produit les variables d'environnement. **C'est ici qu'un `mode` illégal lève `ValueError`, pas à la construction** — comme elle est appelée par `build_options`, l'erreur surgit dans `Runtime.run` |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

L'objet de politique qui, quand le contexte est presque plein, « écrit un [document de handoff](glossary.md#交接书)
et repart sur une nouvelle session » au lieu de compacter.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Désactivé, on retombe sur l'auto-compact |
| `window` | `int` | `default_window()` | Taille supposée de la fenêtre de contexte du modèle |
| `headroom` | `int` | `50_000` | Marge à conserver. Raison : l'auto-compact se déclenche à fenêtre − 33k, le handoff doit passer avant, et « écrire le handoff » consomme lui-même un tour |
| `max_generations` | `int` | `8` | Nombre maximal de générations par étape. **C'est un frein anti-emballement, pas du dimensionnement de capacité** |

| Propriété | Type | Description |
|---|---|---|
| `at` | `@property -> int` | Seuil de handoff `max(10_000, window - headroom)`. **Plancher à 10k** — en dessous, on n'arrive même plus à écrire le document de handoff |
| `warn_at` | `@property -> int` | Position du rappel d'approche `max(1_000, at - 20_000)`, envoyé une seule fois par génération |

!!! warning "Un `window` trop petit provoque des handoffs infinis et brûle de l'argent"
    Si `at` tombe sous le **plancher de démarrage** du rôle (environ 34k mesuré pour le coordinateur), chaque
    nouvelle session dépasse la ligne dès sa première prise de parole ; et comme **un handoff ne consomme pas de
    quota de reprise** (`attempt -= 1`), on tourne à vide indéfiniment. Le seul frein est `max_generations=8` ;
    une fois atteint, `error` est remplacé par un diagnostic invitant à augmenter `window` ou à désactiver le handoff.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Devine la fenêtre de contexte à partir de la **chaîne du nom de modèle** dans les variables d'environnement
`ANTHROPIC_MODEL` ou `ANTHROPIC_DEFAULT_OPUS_MODEL` :

| Condition | Retour |
|---|---|
| Le nom contient le mot isolé `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| Le nom contient `haiku` | `200_000` |
| Le reste (**y compris quand aucune des deux variables n'est définie**) | `1_000_000` |

**La valeur par défaut est agressive.** Surestimer n'est pas une erreur dure : l'API renvoie `prompt is too long`,
`Runtime` reconnaît ce signal (le `is_overflow` interne) et déclenche un handoff sur-le-champ — mais le handoff
de cette génération-là est une version dégradée.

---

## Documents {#文书}

Sources : [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatre dataclasses, toutes sur le même principe : « parser une réponse du modèle en un nombre fixe de sections,
puis écrire sur disque ». Forme commune : `parse()` parse, `missing()` / `complete()` vérifient la complétude,
`to_markdown()` pour l'humain, `prompt_block()` pour le modèle en aval, `write()` / `load()` pour l'écriture et la
relecture.

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

Le [brief](glossary.md#需求确认书), **exactement quatre sections**, dans l'ordre fixe
`goal` → `accept` → `bounds` → `unknowns` ; les noms de sections en chinois sont respectivement 「目标」(objectif),
「验收标准」(critères d'acceptation), 「边界」(limites), 「未知与假设」(inconnues et hypothèses).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `goal` | `str` | `""` | Objectif |
| `accept` | `str` | `""` | Critères d'acceptation |
| `bounds` | `str` | `""` | Limites |
| `unknowns` | `str` | `""` | Inconnues et hypothèses |
| `path` | `Path \| None` | `None` | Emplacement d'écriture sur disque. `compare=False`, n'entre pas dans la comparaison d'égalité |

| Méthode | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Noms chinois** des sections manquantes, directement affichables |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parse les quatre sections depuis la réponse du modèle. **Retire d'abord les blocs de code délimités** ; ce qui n'est pas retrouvé reste vide |
| `to_markdown` | `() -> str` | Document complet avec en-tête de métadonnées, les sections vides s'écrivent `"(未填)"` |
| `prompt_block` | `() -> str` | Version compacte pour l'aval, **ne contient que les sections non vides**, sans métadonnées |
| `write` | `(path: str \| Path) -> Path` | Crée le répertoire parent, écrit, met `self.path` au chemin résolu et le retourne |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Retourne `None` si le fichier n'existe pas ou en cas d'`OSError`. **Restaure le placeholder `"(未填)"` en chaîne vide** |

Règles de parsing (là où se concentrent les pièges) :

- Au retrait des blocs délimités, **en cas de ``` ou de `~~~` non refermé, tout est jeté à partir de là** — en
  conditions réelles, le clarificateur colle parfois tout le code dans sa réponse. Quand la sortie du modèle est
  tronquée, aucune des sections suivantes n'est parsée, `complete()` vaut donc `False`, et le gate renvoie à la case départ.
- La regex de titre tolère `## 目标` / `**目标**` / `目标:` / `3. 边界`, et tolère aussi que le corps suive
  directement le titre.
- La table d'alias est compilée par longueur décroissante, sinon « 未知 » avalerait « 未知与假设 » en premier.
- En cas de répétition d'une même section, **on prend la première qui a du contenu**.
- Si, en éditant le brief à la main, on recopie le placeholder `"(未填)"` de `to_markdown()`, la section compte
  toujours comme manquante.

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

Le [document de handoff](glossary.md#交接书) écrit lors d'un [handoff](glossary.md#换代), cinq sections.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `doing` | `str` | `""` | Ce qui est en cours. **Obligatoire** |
| `decided` | `str` | `""` | Ce qui a été décidé |
| `deadends` | `str` | `""` | Les impasses |
| `next` | `str` | `""` | L'étape suivante. **Obligatoire** |
| `scene` | `str` | `""` | L'état des lieux |
| `step` | `str` | `""` | Sert uniquement à l'en-tête du document, **n'entre pas dans le parsing** |
| `path` | `Path \| None` | `None` | Emplacement d'écriture sur disque |

**Seules deux sections sont obligatoires : `doing` et `next`** — exiger que « les impasses » soit non vide
pousserait le modèle à inventer.

| Membre | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Ne contrôle que les deux sections obligatoires** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Le corps porte-t-il la marque de dégradation `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Réutilise le découpeur de `Brief` |
| `to_markdown` | `() -> str` | Les sections vides s'écrivent `"(空)"` |
| `prompt_block` | `() -> str` | **L'en-tête dit explicitement au repreneur « tu reprends »**, pour l'empêcher d'aller réclamer le contexte à quelqu'un |
| `write` | `(path) -> Path` | Comme `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Comme `Brief.load` |

Dans le même module, trois membres **non exportés mais sémantiquement essentiels** : `is_overflow(*texts)` détecte
`prompt is too long`, `context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, etc., et transforme une « erreur dure » en « handoff immédiat » ;
`HANDOFF_PROMPT` est le prompt qui fait écrire le handoff par **la session courante elle-même** (avec les deux
placeholders `{used}` et `{window}`, **ce n'est pas un nouveau rôle** — elle seule possède ce contexte) ;
`degraded(step, prompt, *, why="")` fabrique mécaniquement un document quand le handoff n'a pas pu être écrit,
en fourrant dans `scene` les **1200** premiers caractères de la tâche d'origine.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

L'objectif et la liste de verdict du [gardien d'objectif](glossary.md#目标看守).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `statement` | `str` | `""` | Énoncé de l'objectif |
| `checks` | `list[str]` | `[]` | Liste de verdict, un item par ligne |
| `path` | `Path \| None` | `None` | Emplacement d'écriture sur disque |

| Membre | Signature | Description |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Les items de `checks` marqués `[此环境无法验证:…]`. **Condamnés à ne jamais passer dès l'instant où l'objectif est fixé** |
| `missing` | `() -> list[str]` | Exige `statement` non vide **et** `checks` non vide |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` un item par ligne, les marqueurs `-` / `*` / `1.` sont retirés automatiquement |
| `to_markdown` | `() -> str` | Liste vide → `"(空)"` |
| `prompt_block` | `() -> str` | Version compacte pour l'aval |
| `write` / `load` | Comme `Brief` | Écriture sur disque et relecture |
| `amend` | `(extra: str) -> Goal` | **Ajoute sans écraser** : concatène `"\n\n(已修改)" + extra` après `statement`, retourne `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Le résultat d'un tour de verdict du [juge](glossary.md#判定者), **exactement trois sections** :
conclusion / justification / items non passés.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"` ; `""` si non parsable |
| `reason` | `str` | `""` | Justification |
| `failed` | `list[str]` | `[]` | Les items de la liste qui ne passent pas |

| Membre | Signature | Description |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | A-t-on réussi à parser une conclusion. **`ok=False` doit être traité comme « non atteint », jamais comme atteint** |
| `parse` | `@classmethod (text) -> Verdict` | Voir ci-dessous |
| `feedback` | `() -> str` | Ce qui est renvoyé à l'exécutant : uniquement « ce qui manque », pas la solution |

Ordre de reconnaissance de `parse` :

1. D'abord, prendre la section de titre 「结论」/「判定」.
2. En l'absence de section de titre, sur le texte entier après strip : `fullmatch(r"1|true")` → atteint ;
   `fullmatch(r"0|false")` → pas encore.
3. Sinon, chercher dans le texte de conclusion le premier mot trouvé selon la table des mots d'état
   (**les mots longs d'abord**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 sont tous rangés sous `unreachable`** —
   vécu en vrai : plateforme cible macOS, exécution dans un conteneur Linux, le juge a regardé la branche du code
   source et a prononcé la réussite.
4. Toujours rien → chercher un `\b1\b` isolé → atteint, `\b0\b` → pas encore.
5. Rien ne correspond → `state=""`, `ok=False`.

`unreachable` et `not_yet` **sont deux conclusions différentes** : la première emprunte la voie « s'arrêter et
demander à un humain », pas celle de « refaire un tour ».

---

## Couche hook {#hook}

Source : [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Cette couche est la **frontière d'exécution** de flower : quels outils le thread principal n'a pas le droit de toucher, comment rogner un résultat trop long, quel rôle part dans un worktree indépendant — tout est imposé par les hooks du SDK, **pas par le prompt**. La raison est directe : un prompt est une suggestion, le modèle peut l'ignorer. Mesuré : même avec un system prompt qui écrit explicitement « n'utilise pas de worktree », l'injection d'`isolate_guard` s'applique quand même (le modèle passe `None`, ce qui atterrit est `'worktree'`).

Neuf exports : cinq fabriques de guard qui retournent un `HookMatcher` (`whitelist_guard` peut retourner `None`), un assembleur, un fusionneur, deux fonctions de marquage d'isolation.
Il n'y a pas besoin de les brancher à la main — [`Runtime`](#runtime) les monte automatiquement d'après l'`AgentSpec`. Le branchement manuel n'est nécessaire que si l'on pilote le SDK soi-même (sans passer par `Runtime`).

**La détection du thread principal passe par une seule fonction** : `_is_main_thread(data) = not data.get("agent_id")` — les données de tool-lifecycle hook d'un subagent portent un `agent_id`, celles du [thread principal](glossary.md#主线程) non.
Tous les guards « n'intercepter que le thread principal » reposent sur cette ligne.

Constantes de groupes d'outils (niveau module, non exportées, mais elles déterminent les matchers par défaut) :

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Aide-mémoire : quel guard sur quel événement SDK {#hook-速查表}

| Fonction | Événement hook SDK | matcher | Ce qui est intercepté | Ce qui est retourné | Qui l'installe |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | ceux de `Bash\|Write\|Edit\|NotebookEdit` qui **ne sont pas dans `allowed_tools`** | **uniquement le thread principal** appelant un outil interdit | `permissionDecision: "deny"` + motif | `Runtime._attempt`, **uniquement si `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (modifiable via `tools=`) | **uniquement le thread principal** qui met la main à la pâte ; si `allow_glance=True`, un `Bash` qui passe `is_ephemeral()` est laissé passer | `deny` + « délègue à un subagent » | `workbench_hooks(delegate_only=True)`, **uniquement si le `Runtime` a un workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sans `cwd` ni `isolation`, et `subagent_type` marqué par `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injecte `isolation="worktree"`) | `workbench_hooks`, **uniquement si `agents` contient un rôle marqué** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` situé sous `workbench.root` | `{}` (l'effet de bord est `workbench.refresh()`) | `workbench_hooks`, toujours installé |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | les **champs chaîne** de `tool_response` faisant ≥ `threshold` caractères ; la lecture du répertoire de spill lui-même est laissée passer | `updatedToolOutput` (spill + un pointeur d'une ligne + les 400 premiers caractères) | `workbench_hooks`, **uniquement si `spill_threshold` est vrai** |

**Le corollaire clé de ce tableau** : avec `Runtime(workbench=False)`, `workbench_hooks` n'est pas installé du tout ;
et pour un coordinateur en `delegate_only=True`, `whitelist_guard` est également sauté — **le thread principal n'a plus le moindre mur**.
Voir l'avertissement de la section [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Rendre `allowed_tools` réellement exclusif pour les quatre outils qui mettent la main à la pâte.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obligatoire, argument positionnel | on passe généralement `spec.allowed_tools` directement |
| `role` | `str` | `"这个角色"` | la manière dont le refus se désigne lui-même. `Runtime` passe `spec.name` |

- **Monté sur `PreToolUse`**, le matcher est `"|".join(banned)`, où `banned` = ceux de `Bash` `Write` `Edit` `NotebookEdit` qui ne sont pas dans `allowed`.
- En cas de correspondance : `permissionDecision: "deny"`, avec un texte du genre : « XX n'a pas YY. **C'est intentionnel, ce n'est pas une configuration oubliée.** Écris ta conclusion dans le corps de ta réponse, le framework ira la chercher là — n'essaie pas de contourner par une autre formulation. »
- **N'intercepte que le thread principal de la session**, les subagents passent — les outils d'un subagent sont déterminés par `AgentDefinition.tools`.
- Retourne **`None`** quand il n'y a rien à intercepter (par exemple un rôle comme `worker()` qui a la panoplie complète) ; l'appelant décide alors de l'installer ou non.

**Pourquoi il doit exister** : `allowed_tools` est une **liste de dispense d'approbation, pas une liste blanche exclusive**. Deux preuves mesurées : un juge à qui l'on avait donné un objectif a lancé 11 fois `Bash` ; dans la sonde à $0.1, un agent avec `allowed_tools=["Read"]` appelait quand même `Write`/`Bash`.
Donc le « pas d'outil d'écriture » de `clarify()` / `judge()` **tient à ce hook**, pas à la liste blanche elle-même.

L'avantage est qu'il dérive d'`allowed_tools` : `judge(can_run=True)` conserve donc automatiquement `Bash` tout en interceptant `Write`/`Edit` — sans interrupteur supplémentaire.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Le thread principal met la main à la pâte → refus, avec l'indication du chemin à suivre.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. C'est une chaîne regex, pas une liste |
| `allow_glance` | `bool` | `False` | si `True`, laisse passer quand `tool_name == "Bash"` et [`is_ephemeral(command)`](#is-ephemeral) est vrai |

- **Monté sur `PreToolUse`**, le matcher est exactement `tools`.
- Le thread principal appelle un de ces quatre outils → deny, et le motif **indique quoi faire ensuite** : déléguer à un subagent via l'outil `Agent`, en écrivant dans la tâche l'objectif et les critères d'acceptation, et en lui demandant d'écrire les productions longues dans `.flower/artifacts/` et de ne renvoyer que chemins et conclusions.
- Les subagents passent systématiquement.

La différence avec `whitelist_guard` est la **formulation** : les deux interceptent le même ensemble d'outils, mais celui-ci dit « délègue », ce qui est plus juste.
Un rôle en `delegate_only=True` n'installe donc que celui-ci ; installer les deux enverrait au modèle deux consignes contradictoires.

Le critère de passage d'`allow_glance=True` et le « ce résultat sera-t-il rogné » sont **la même fonction** ([`is_ephemeral`](#is-ephemeral)) — l'ensemble laissé passer doit être égal à l'ensemble qui expire ; modifier l'un oblige à modifier l'autre.

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

Les résultats d'outil qui dépassent le seuil sont **[spillés](glossary.md#落盘) sur-le-champ**, le contexte ne garde qu'un pointeur d'une ligne — plutôt que d'attendre que le contexte soit plein pour compacter après coup.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, argument positionnel | le répertoire de spill est `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | au-delà de combien de caractères on spille |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (défaut) = les résultats des subagents sont eux aussi spillés |

- **Monté sur `PostToolUse`**, retourne `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <rogné>}}`.
- Le nom du fichier de spill est les 16 premiers caractères du `sha256` du contenu + `.txt` ; dans le contexte il est remplacé par un pointeur d'une ligne + les **400 premiers caractères**.
- `updatedToolOutput` **doit conserver la structure de sortie de l'outil d'origine**, donc on ne remplace que les **champs chaîne** trop longs du dict ; **on ne touche jamais aux listes** (elles peuvent contenir des blocs image). Une structure incorrecte est rejetée (le texte original reste, sans erreur).
- **La lecture du fichier de spill lui-même doit être laissée passer** — sinon « lis-le avec `Read` » est une phrase creuse : le texte relu est à nouveau spillé, boucle infinie.
  Rencontré en conditions réelles : le modèle a essayé cinq formulations pour contourner.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Dès qu'on écrit quelque chose dans le [workbench](glossary.md#工作台), `INDEX.md` est rafraîchi, et l'agent suivant sait dès son ouverture que ça existe.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, argument positionnel | périmètre de décision et cible du rafraîchissement |

**Monté sur `PostToolUse`**, matcher `"Write|Edit"`. Si `tool_input["file_path"]` résolu tombe sous `workbench.root`, appelle `workbench.refresh()`. **Retourne toujours `{}`** — il ne modifie rien, il n'a que des effets de bord.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Attribue à chaque subagent, selon son rôle, un git worktree indépendant : c'est l'[isolation](glossary.md#隔离).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obligatoire, argument positionnel | table des rôles, sert à vérifier si le `subagent_type` est marqué |
| `on_inject` | `Any` | `None` | callback optionnel, appelé sous la forme `on_inject(subagent_type, description)` |

**Monté sur `PreToolUse`**, matcher `"Agent"`. L'injection n'a lieu que si trois conditions sont réunies : `tool_name == "Agent"`, `tool_input` **n'a ni `cwd` ni `isolation`**, et le rôle correspondant au `subagent_type` est marqué par `isolated()`. Dans ce cas il retourne `permissionDecision: "allow"` + `updatedInput` (met `isolation` à `"worktree"`).

`isolation` et `cwd` sont **mutuellement exclusifs** dans l'outil `Agent` — si le modèle a lui-même spécifié un `cwd`, on le respecte.
« Faut-il isoler » est une **propriété du rôle**, pas un interrupteur global, ni une décision prise à chaque délégation ; un rôle qui n'a pas besoin d'isolation ne se voit ajouter aucun octet.

**Activer l'isolation impose de sortir le [workbench](glossary.md#工作台) du dépôt.** Un agent isolé ne peut pas écrire dans le checkout partagé, donc le workbench doit pointer hors du dépôt via `home=`. `starter_flow(isolate=True)` utilise `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` utilise `<run_dir>/workbench` — les deux sont hors du dépôt, **mais ce ne sont pas le même répertoire**, ne les mélangez pas.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marquer une définition de subagent comme « a besoin d'un espace de travail indépendant », et relire ce marquage.

| Fonction | Paramètre | Défaut | Description |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obligatoire | la définition à marquer. **Retourne le même objet** |
| | `flag: bool` | `True` | argument positionnel. `False` = retirer le marquage |
| `wants_isolation` | `agent: AgentDefinition \| None` | obligatoire | accepte `None`, retourne alors `False` |

Le marquage est un attribut côté Python `_flower_isolate` posé via `object.__setattr__`, **pas un champ de dataclass** — le SDK sérialise avec `asdict()`, qui ne reconnaît que les champs déclarés, donc ce marquage ne fuit pas jusqu'au CLI (mesuré).

**Le coût** : un `dataclasses.replace()` sur une `AgentDefinition` perd ce marquage, et l'isolation devient silencieusement inopérante.

`worker(isolate=True)` passe en interne par `isolated()`.

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

Installe en une fois les quelques hooks dont le workbench a besoin. C'est ce qu'appelle `Runtime._attempt`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, argument positionnel | passé à `index_guard` et `spill_guard` |
| `delegate_only` | `bool` | `True` | `delegate_guard` n'est installé que si `True` |
| `spill_threshold` | `int \| None` | `4000` | `spill_guard` n'est installé que si la valeur est vraie |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | `isolate_guard` n'est ajouté que si **au moins un** est marqué par `isolated()` |
| `allow_glance` | `bool` | `False` | transmis à `delegate_guard(allow_glance=)` |

Ce qui est produit :

- `PreToolUse` : `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]` ;
  s'il y a un rôle marqué → ajout d'`isolate_guard(agents)`.
- `PostToolUse` : toujours `[index_guard(workbench)]` ; si `spill_threshold` est vrai → ajout de `spill_guard(workbench, threshold=spill_threshold)`.
- **Les clés d'événement dont la liste est vide sont supprimées**, on ne retourne pas de liste vide.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatène** plusieurs groupes de configuration de hooks par nom d'événement.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | argument variadique | autant de groupes qu'on veut. Les groupes `None` sont ignorés |

Utilise `extend`, **sans déduplication** — passer deux fois le même guard l'installe deux fois. `Runtime` s'en sert pour fusionner `spec.hooks`, `workbench_hooks(...)` et `whitelist_guard`.

---

## Workbench {#工作台}

Source : [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

Le répertoire de travail où l'on écrit sur disque : trois sous-répertoires + un index. L'index est **injecté dans le system prompt**, donc l'agent sait à chaque tour ce qu'il a en main.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `Path` | obligatoire, argument positionnel | l'espace de travail. `__post_init__` le résout |
| `dirname` | `str` | `".flower"` | nom du répertoire du workbench, relatif à `workspace` |
| `max_index_entries` | `int` | `40` | **ne concerne que `prompt_block()`** : combien d'entrées par catégorie au maximum dans le bloc injecté dans le system prompt, le reste étant réduit à une ligne « … et N autres ». `INDEX.md` lui-même n'est pas limité et liste tout |
| `home` | `Path \| None` | `None` | s'il est fourni, il sert de `root` et **`dirname` est ignoré**. Résolu lui aussi quand il n'est pas `None` |

| Membre | Signature | Description |
|---|---|---|
| `root` | `@property -> Path` | `home` s'il est fourni, sinon `workspace / dirname` |
| `external` | `@property -> bool` | si `root` est **en dehors** de `workspace`. Doit être `True` en mode isolé |
| `scripts` | `@property -> Path` | `root / "scripts"`, les scripts destinés à être relancés |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, les productions longues de plus de 2000 caractères |
| `notes` | `@property -> Path` | `root / "notes"`, les décisions clés, un fichier par décision |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | le chemin montré au modèle : relatif dans l'espace de travail, absolu en dehors |
| `ensure` | `() -> Workbench` | crée les trois répertoires, retourne `self` (chaînable : `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(chemin affiché, description, nombre d'octets)`. `rglob("*")` récursif, ignore les fichiers commençant par `.` |
| `refresh` | `() -> str` | réécrit `INDEX.md` et retourne son contenu |
| `prompt_block` | `() -> str` | **le bloc injecté dans le system prompt**. Volontairement court — il est là à chaque tour |

Format d'auto-description d'un script : `# desc: une phrase` dans les 8 premières lignes (les marqueurs `//` et `--` sont aussi reconnus), avec repli sur le premier commentaire non vide ou la première ligne de la docstring (tronquée à 100 caractères).

Les trois règles injectées par `prompt_block()` :

1. Les scripts destinés à être relancés vont dans `scripts/`, avec `# desc:` en première ligne.
2. Les productions de plus de **2000 caractères** vont dans `artifacts/`, la conversation ne reçoit que le chemin et la conclusion.
3. Les décisions clés vont dans `notes/`, un fichier par décision.

Quand `external=True`, `prompt_block()` insère en plus une phrase « accède-y par chemin absolu ».

**Un subagent n'hérite pas de l'index.** Celui-ci passe par le `system_prompt.append` au niveau de la session, alors qu'un subagent a son propre system prompt (mesuré à $0.2461). Les deux points « écrire les productions longues dans `artifacts/` » et « où se trouve le workbench » doivent donc être retransmis par le [coordinateur](glossary.md#协调者) dans le [brief de tâche](glossary.md#任务书) — **c'est le seul canal**, ce n'est pas de la redondance.
`WORKER_RULES` **ne l'écrit délibérément pas** : le vrai chemin est généré par `Workbench`, le coder en dur serait faux.

---

## Session store {#会话存储}

Source : [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Trois niveaux d'héritage : `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **utilise toujours le niveau le plus externe** ; les politiques des trois niveaux se pilotent par les paramètres du constructeur.

Chaque niveau s'occupe d'une chose : écrire sur disque, [trimmer](glossary.md#裁剪) selon le volume et la valeur, [pruner](glossary.md#剪除) selon « est-ce une erreur ».
Le trim et le prune ont tous deux lieu au moment de **`load()`** (c'est-à-dire quand le resume réinjecte l'historique dans le modèle) ; l'enregistrement brut dans SQLite n'est pas modifié d'un octet.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implémente le protocole `SessionStore` du SDK, trois tables `entries` / `meta` / `summaries`.
La clé de store est `project_key/session_id[/subpath]` — **le transcript d'un sous-agent se distingue par le subpath**.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `path` | `str \| Path` | obligatoire, argument positionnel | fichier de base de données. La connexion utilise `check_same_thread=False` |

| Méthode | Signature | Description |
|---|---|---|
| `append` | `async (key, entries) -> None` | déduplication idempotente par uuid (d'abord ce qui est déjà en base, puis les doublons internes au lot). Lors d'un rejeu de lot complet : **ni avancement du mtime, ni fold de summary en double** ; seul le transcript principal (`subpath is None`) participe au summary |
| `projects` | `() -> list[str]` | les `project_key` réellement présents en base. **Le SDK les dérive du cwd ; confirmez avec ceci avant d'interroger, ne devinez pas** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **synchrone, ne lit pas le payload**, ne consulte qu'une ligne de meta. Sert à la « continuité sur le même chemin » — reprendre une session inexistante ne casse qu'une fois le sous-processus démarré |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | la taille de contexte réellement vue par le modèle au dernier tour, `0` si introuvable. Ne parcourt à rebours que les `scan` dernières entrées ; compte les trois postes `input + cache_read + cache_creation` (ne regarder que `input_tokens` sous-estime lourdement) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | trié par seq ; retourne `None` s'il n'y a aucune ligne |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | uniquement les transcripts principaux |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | liste les résumés de session |
| `delete` | `async (key) -> None` | supprimer un transcript principal **supprime en cascade ceux des sous-agents**, pour éviter les orphelins |
| `list_subkeys` | `async (key) -> list[str]` | liste les sous-transcripts de cette session |
| `close` | `() -> None` | ferme la connexion |

Le `_next_mtime` interne garantit une **stricte monotonie** — `list_sessions` et le sidecar de summary partagent cette horloge, sinon le chemin rapide de détection de staleness du SDK se trompe.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `keep_recent` | `int` | `20` | les N derniers `tool_result` gardent leur texte intégral |
| `min_chars` | `int` | `2000` | les résultats courts ne valent pas la peine d'être trimmés |
| `spill_dirname` | `str` | `".flower/spill"` | **relatif à `workspace`, doit être dans l'espace de travail** — sinon le `Read` de l'agent n'y accède pas |
| `enabled` | `bool` | `True` | vaut `False` avec `Runtime(trim=False)` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | produit la ligne de pointeur qui remplace le texte |

**Les deux répertoires de spill ne sont pas le même.** `spill_guard` écrit dans `<workbench.root>/spill/` (qui peut être hors de l'espace de travail) ; `TrimPolicy.spill_dirname` écrit dans `<workspace>/.flower/spill/` (**qui doit être dans l'espace de travail**).
Ils correspondent respectivement au « rognage sur-le-champ » et au « rognage au resume » ; la différence de répertoire est intentionnelle, ne les fusionnez pas.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Politique d'expiration des résultats de [commandes éphémères](glossary.md#一次性命令).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | désactivé, le marquage d'expiration n'a pas lieu du tout |
| `keep_recent` | `int` | `6` | les N derniers sont exemptés. **Bien plus petit que le 20 de `TrimPolicy`** |
| `max_chars` | `int` | `2000` | au-delà, on saute et on laisse `TrimPolicy` archiver |
| `text` | `str` | voir la signature | texte de remplacement, deux emplacements `{cmd}` et `{age}` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | applique `text` pour produire le texte de remplacement |

**Ne s'applique qu'aux résultats de l'outil `Bash`**, et seulement si la commande correspond à la liste blanche des commandes éphémères. **`Read` n'en fait pas partie** — le contenu d'un fichier ne se dégrade pas avec le temps au point d'induire en erreur. Le contenu expiré **n'est pas spillé**, il est jeté.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Détermine si une commande Bash est une [commande éphémère](glossary.md#一次性命令).
**Le critère de passage de `delegate_guard` et le critère d'expiration du trim partagent cette même fonction** — l'ensemble des commandes que le coordinateur peut exécuter lui-même doit être égal à l'ensemble des résultats marqués comme expirés. Laisser passer sans trimmer : un `git status` périmé occupe le contexte à perpétuité et induit en erreur ; trimmer sans laisser passer : le coordinateur délègue un subagent pour un `ls`, 4,3k de coût de démarrage pour quelques dizaines de caractères.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `cmd` | `str` | obligatoire, argument positionnel | ligne de commande complète |

Ordre de décision :

1. Vide / entièrement blanc → `False`.
2. Substitution de commande (`$(`, backticks, `<(`, `>(`) ou écriture « qui modifie l'état » détectée → `False`.
3. Après retrait des redirections sûres (`2>&1`, `&> /dev/null`, etc.), il reste un `>` ou un `<` → `False`.
4. Après retrait de `&&` / `||` / `;` / `|`, il reste un `&` isolé (exécution en arrière-plan) → `False`.
5. Découpage sur `&&` / `||` / `;` / `|`, **chaque segment doit correspondre à la liste blanche**.

Grandes catégories de verbes de la liste blanche : sous-commandes `git` en lecture seule (`status` `diff` `log` `show` `branch` `rev-parse`, etc.), informations sur les répertoires et le système (`ls` `pwd` `df` `du` `date` `whoami` `env`, etc.), processus et conteneurs (`ps` `top` `lsof` `docker ps` `kubectl get`, etc.), consultation de fichiers (`cat` `head` `tail` `wc` `stat` `find` `tree`), recherche de chemins (`which` `whereis` `command -v` `type`), traitement de texte (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff`, etc.).

Même si le verbe est dans la liste blanche, ces écritures sont bloquées : `xargs`, `exec`, `eval`, `source`, `tee`, `find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` et `print >` dans `awk`, `git branch -D/-d/-m`, `git * --force/--hard/--prune`.

La première version refusait sans distinction toutes les commandes composées, ce qui **rendait le glance totalement inopérant en conditions réelles** (les trois tentatives du coordinateur ont été bloquées) ; d'où le passage à une décision segment par segment.

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `path` | `str \| Path` | obligatoire | fichier de base de données |
| `workspace` | `str \| Path` | obligatoire | base de référence du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | à défaut, `TrimPolicy()` par défaut |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | à défaut, `EphemeralPolicy()` par défaut |

Attributs publics : `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

L'ordre dans `load()` : `super().load()` → vidage de `last_report` → si `ephemeral.enabled`, `expire()` → si `policy.enabled`, `trim()`. **Avec `enabled=False`, l'étape est entièrement sautée.**

| Méthode | Description |
|---|---|
| `expire(entries)` | remplace **uniquement le texte** des résultats `Bash` périssables expirés, **le bloc est conservé**. La commande est retrouvée dans le `tool_use` du message assistant précédent ; saute `isCompactSummary` / `isMeta` ; saute ce qui dépasse `max_chars` (laissé à `trim`) ; les `keep_recent` derniers sont exemptés. Écrit `last_report["expired"]` |
| `trim(entries)` | le texte des `tool_result` de `>= min_chars` est spillé dans `<workspace>/<spill_dirname>/<16 premiers caractères du sha256>.txt`, le contenu du bloc étant remplacé par un pointeur ; les `keep_recent` derniers sont exemptés. Écrit `cleared` / `kept` / `chars_saved` dans `last_report` |

**Ne trimme que le texte pur** : les blocs `image` / `document` sont laissés tels quels.

**Deux lignes rouges structurelles** : le **bloc `tool_result` lui-même doit rester**, on ne peut remplacer que son content (un de moins et c'est « Missing Tool Result Block ») ; les entrées `isCompactSummary` ne doivent pas être touchées.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Rend `store.last_report` sous forme d'une ligne en chinois, pour les logs de l'UI.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obligatoire, argument positionnel | accepte aussi la sous-classe `PruningSessionStore` |

Trois sorties possibles : aucune action → `"未裁剪"` ; expiration seule → `"N 个时效性结果标记为过期"` ;
sinon `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, où X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    heal_orphans: bool = True
    orphan_text: str = "[这一步被打断了,没有结果。需要的话重做。]"
    keep_denials: int = 1
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | retire les messages d'erreur API synthétiques (résidus de coupure) |
| `neutralize_interrupts` | `bool` | `True` | remplace par une note neutre les `tool_result` résiduels d'une interruption |
| `interrupt_text` | `str` | voir la signature | texte de la note neutre |
| `heal_orphans` | `bool` | `True` | ajoute un résultat synthétique aux appels orphelins qui ont un `tool_use` sans `tool_result` |
| `orphan_text` | `str` | voir la signature | texte du `tool_result` ainsi ajouté |
| `keep_denials` | `int` | `1` | conserve les N derniers appels d'outil refusés |

`heal_orphans` traite le **400 systématique au resume après une interruption** : l'interruption coupe à une frontière de message, et le `tool_use` en vol à ce moment-là peut n'être suivi d'aucun `tool_result`, alors que l'API exige qu'ils aillent par paires — cet historique cassé reste dans le transcript, et **chaque** resume ultérieur se fait rejeter à cause de lui. `heal_orphans()` insère une entrée `user` juste après l'assistant contenant l'orphelin pour compléter le résultat manquant, et redirige le `parentUuid` qui pointait vers cet assistant vers l'entrée ajoutée, préservant la continuité de la chaîne (`prune.py:95-147`). **Compléter plutôt que supprimer** : supprimer l'orphelin obligerait à recoudre la chaîne parent-enfant de l'assistant, et le même message peut contenir d'autres blocs normaux, du texte et du thinking, faciles à emporter au passage (`prune.py:195-204`).

La raison de `keep_denials` : un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information, mais il occupe de la place (mesuré une fois à 273 caractères = 93 caractères de refus + 180 caractères du **texte de la commande morte**). Plus grave, **il induit en erreur** — mesuré : après avoir lu quelques « n'utilise pas Bash directement », le coordinateur n'essaie même plus le `git status` pourtant autorisé, il a appris l'impuissance acquise.
**On en garde 1 par défaut et non 0** : le refus le plus récent empêche le modèle de retenter en boucle la même commande bloquée dans le même tour.

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**Le store par défaut de `Runtime`.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `path` | `str \| Path` | obligatoire | fichier de base de données |
| `workspace` | `str \| Path` | obligatoire | base de référence du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | politique de trim |
| `prune` | `PrunePolicy \| None` | `None` | politique de prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | politique d'expiration |

Trois attributs publics en plus de ceux de la classe parente : `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (d'abord `expire` + `trim`) → `self.prune(entries)`. `prune` fait trois choses :

1. **Retirer les appels refusés trop anciens** : la détection s'appuie sur le marqueur structurel `toolDenialKind == "permission-rule"` du harness (plus fiable que de matcher le texte du refus), garde les `keep_denials` derniers, et retire pour les autres le bloc `tool_use` **et** le bloc `tool_result`. Quand un même message assistant contient plusieurs `tool_use`, **seuls ceux concernés sont retirés**, sinon on obtient un « Missing Tool Result Block » ; les blocs texte et thinking sont conservés.
2. **Retirer les messages d'erreur API synthétiques.** Ils restent intacts dans SQLite, ils ne sont simplement pas réinjectés.
3. **Remplacer par une note neutre les `tool_result` résiduels d'une interruption** — seul le texte est remplacé, l'entrée n'est pas retirée.

**L'unique ligne rouge structurelle** : le transcript est une chaîne simple par `parentUuid` ; retirer une entrée oblige à raccrocher ses enfants à l'ancêtre survivant le plus proche.
Le `relink` interne exige que `entries` **soit la liste complète (y compris les entrées à retirer)**, le filtrage étant fait par lui-même — si l'appelant retire d'abord puis passe la liste, la chaîne casse à cet endroit et tout l'historique antérieur est perdu (**déjà rencontré : invisible quand les entrées retirées sont en fin de liste, explosif quand elles sont au milieu**).

**L'ordre des paramètres diffère de celui de la classe parente** : le parent est `(path, workspace, policy, ephemeral)`, la sous-classe est `(path, workspace, policy, prune, ephemeral)` — **le quatrième argument positionnel passe d'`ephemeral` à `prune`**, un passage positionnel se décale silencieusement. Passez toujours par mots-clés.

---

## Résilience {#韧性}

Source : [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

En cas de coupure réseau, on attend en suspens au lieu de sortir en échec. Quatre exports : une dataclass de politique + trois fonctions de sondage utilisables séparément.

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | désactivé, aucune panne n'est réessayée |
| `max_attempts` | `int` | `6` | **la première tentative comprise** |
| `base_delay` | `float` | `4.0` | base du backoff, en secondes |
| `max_delay` | `float` | `120.0` | plafond du backoff, en secondes |
| `probe_timeout` | `float` | `5.0` | timeout d'une sonde |
| `probe_interval` | `float` | `15.0` | attente entre deux sondes |
| `max_offline_wait` | `float` | `3600.0` | durée d'attente maximale en suspens, 1 heure par défaut |
| `retry_unknown` | `bool` | `True` | faut-il réessayer les erreurs non classables |
| `resume_prompt` | `str` | voir la signature | ce qui est dit à la reprise. **Ne contient délibérément aucun détail d'erreur** — le modèle doit savoir « tu as été interrompu, continue », pas s'il s'agissait d'un `ENOTFOUND` ou d'un 503 |

| Méthode | Signature | Description |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplié par `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` avec `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | attend en suspens le retour du réseau. Retourne `True` s'il revient, `False` au-delà de `max_offline_wait`. `notify` est un callback `(str) -> None`, appelé une fois **à la première injoignabilité** et une fois **au rétablissement** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classe un texte d'erreur en trois catégories : `"transient"` / `"fatal"` / `"unknown"`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `text` | `str \| None` | obligatoire, argument positionnel | le message d'erreur original. Vide → retourne `"unknown"` |

**On teste fatal avant transient** — les textes du genre 401 contiennent souvent le mot `connection`, et l'ordre inverse ferait attendre indéfiniment.

| Catégorie | Ce qui correspond |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

L'hôte et le port à sonder, alignés sur `ANTHROPIC_BASE_URL`, par défaut `https://api.anthropic.com` ;
port par défaut `80` (http) ou `443`.

**Face à une passerelle auto-hébergée, il faut sonder celle-ci** — le fait que `api.anthropic.com` réponde ne dit rien sur la passerelle.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `host` | `str` | obligatoire, argument positionnel | nom d'hôte |
| `port` | `int` | obligatoire, argument positionnel | port |
| `timeout` | `float` | `5.0` | secondes |

**Fait uniquement le DNS (`getaddrinfo`) + la poignée de main TCP**, n'envoie pas de HTTP, ne transporte pas d'identifiants, **ne coûte rien**. Toute exception compte comme injoignable.

---

## Événements et interaction {#事件与交互}

Source : [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Un [événement](glossary.md#事件) est la structure stable en laquelle le flux de messages du SDK est aplati.
**La [couche d'interaction](glossary.md#交互层) ne connaît que `Event`, elle n'importe aucun type du SDK** —
c'est la frontière qui permet de changer d'UI sans toucher au cœur. Voir [Changer de couche d'interaction](../guide/interaction.md).

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `kind` | `EventKind` | obligatoire | voir le tableau ci-dessous |
| `text` | `str` | `""` | corps du message |
| `tool` | `str` | `""` | nom de l'outil, uniquement pour `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | informations structurées additionnelles |
| `raw` | `Any` | `None` | objet SDK d'origine, pour creuser plus loin |

`__str__` : pour `tool_call`, c'est `f"[{tool}] {text}"`, sinon `text`, et si `text` est vide, `f"<{kind}>"`.
Donc `print(ev)` est directement lisible.

`EventKind` compte **15** valeurs :

| kind | émis par | Description |
|---|---|---|
| `text` | `normalize` | corps du message assistant |
| `thinking` | `normalize` | bloc de réflexion |
| `tool_call` | `normalize` | appel d'outil. `text` est un résumé de `file_path` / `command` / `pattern`, coupé à 200 caractères |
| `tool_result` | `normalize` | résultat d'outil. `text` coupé à 500 caractères, `payload` porte `tool_use_id` / `is_error` |
| `task` | `normalize` | les trois messages Task. `text` est **vide**, le nom de classe est dans `payload["kind"]` |
| `system` | `normalize` | les autres messages système, `text` est le subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` porte `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | message d'erreur API synthétique, `payload` porte `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Le corps est une entrée, pas une production du modèle**, donc il n'entre pas dans `StepResult.text` |
| `unknown` | `normalize` | non reconnu |
| `retry` | `Runtime` | notification de nouvelle tentative |
| `step` | `Workflow.run` | payload : `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | dans le payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | question posée, **porte aussi « ce que l'humain dit de lui-même »** |

**Les quatre derniers ne sont pas produits par `normalize()`.**

Le `payload` de tous les événements assistant / user porte :

| Clé | Type | Description |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | présent uniquement si `subagent` est vrai |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **C'est l'unique source du critère de [handoff](glossary.md#换代)**, et le chiffre qu'un run long-horizon mérite le plus de voir |

**Le kind `ask` porte à la fois « une question » et « ce que l'humain dit de lui-même ».** Pour ce dernier cas,
`payload["kind"] == "mail"`, et il n'y a **ni `options` ni `remaining`**. L'UI doit d'abord tester
`payload.get("kind")` avant de décider comment rendre, sinon elle affichera une simple phrase comme une
question en attente de réponse et restera bloquée dessus.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Aplatit un message SDK en 0 à N `Event`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `message` | `Any` | obligatoire, positionnel | n'importe quel objet message du SDK |

Branches clés :

- **Message d'erreur API synthétique** (`isApiErrorMessage=True` ou `model == "<synthetic>"`) → un unique
  `Event("error", payload={"synthetic": True})`. **C'est délibéré** — sinon le texte de déconnexion serait pris
  pour du corps de message, entrerait dans `StepResult.text` et serait transmis à l'étape suivante.
- `AssistantMessage` → `kind="text"` ; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<résumé>, tool=block.name, payload={"id", "input"})`.
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`.
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`.
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`.

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

Une question posée à l'humain.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `id` | `str` | obligatoire | sert à localiser la question au moment de répondre |
| `question` | `str` | obligatoire | corps de la question |
| `options` | `list[str]` | `[]` | choix proposés. L'humain peut aussi ne rien choisir et taper sa propre réponse |
| `asked_at` | `float` | `time.time()` | instant de la question |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | corps de la réponse |

| Membre | Signature | Description |
|---|---|---|
| `waited_s` | `@property -> float` | depuis combien de temps on attend |
| `event` | `(remaining: int = 0) -> Event` | produit `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

Un **serveur MCP in-process** (deux outils) plus un jeu de méthodes destinées à l'UI. Côté modèle, on ne voit
que `mcp__human__ask` et `mcp__human__inbox`. Tous les paramètres du constructeur sont keyword-only.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | sortie du mode **push**. Si vous le fournissez, `Workflow.run` ne recâblera rien |
| `max_asks` | `int \| None` | `None` | **nombre illimité**. Un nombre en fait un quota dur, `0` = interdiction de poser des questions (tout automatique / CI). En cas de dépassement, l'outil **refuse directement, sans bloquer** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutes. `None` = attendre indéfiniment ; **`<= 0` = ne pas attendre, toute question tombe immédiatement à vide** |
| `log_path` | `str \| Path \| None` | `None` | questions/réponses **ajoutées** sur disque, sans occuper le contexte |
| `amend_path` | `str \| Path \| None` | `None` | ce que l'humain dit en cours de run est ajouté à ce fichier (en général le brief). **Sans écriture sur disque, ça ne survit pas à la frontière d'étape** — l'étape suivante est une nouvelle session, qui ne lit que le gel |
| `over_budget_text` | `str` | constante du module | texte renvoyé au modèle en cas de dépassement de quota |
| `timeout_text` | `str` | constante du module | texte renvoyé au modèle en cas de timeout |
| `declined_text` | `str` | constante du module | texte renvoyé au modèle quand la question est passée |

Attributs publics : les huit homonymes des paramètres du constructeur, plus `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**les exceptions levées par le callback UI sont collectées ici, sans interrompre le run**).

| Membre | Signature | Description |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | à passer tel quel à `AgentSpec.mcp_servers`. **La clé doit correspondre au nom du serveur**, d'où le fait que ce soit fourni ici |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | bloque en attendant l'humain. **Ne lève jamais d'exception hors `CancelledError`** — l'absence de réponse est aussi une réponse, à distinguer via `ask.state` |
| `send` | `(text: str) -> Mail \| None` | l'humain dit quelque chose de lui-même. **Appelable depuis n'importe quel thread**. N'interrompt pas l'agent ; appelle automatiquement `amend()` en interne |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | ajoute dans `amend_path`. Renvoie si l'écriture a vraiment eu lieu (pas de chemin configuré, texte vide, `OSError` → `False`) |
| `pending_mail` | `() -> list[Mail]` | les mails non encore récupérés |
| `remaining` | `@property -> int` | combien de questions restent. **Renvoie `-1` quand `max_asks=None`**, ni 0 ni l'infini |
| `pending` | `() -> list[Ask]` | les questions actuellement en attente de réponse |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | pour le mode **pull**. Renvoie `None` en cas de timeout, lève si annulé |
| `answer` | `(ask_id: str, text: str) -> bool` | répondre. `False` = cette question n'attend plus (timeout / déjà répondue) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | passer, et laisser le modèle juger lui-même |
| `transcript` | `() -> str` | le markdown de l'historique questions/réponses |

**Choisissez l'un des deux modes de récupération** : **push** — construire `HumanChannel(on_event=...)` ;
**pull** — `await channel.next_ask()`. `Workflow.run` ne câble automatiquement que si `channel.on_event is None`,
donc si vous l'avez fourni vous-même il ne sera pas écrasé.

**Multi-thread** : `answer` / `decline` / `send` passent en interne par `loop.call_soon_threadsafe`,
un appel direct depuis un backend Web ou un thread d'entrée TUI est la norme.

Les trois sémantiques « 0 / None » sont toutes différentes, ne les confondez pas : `max_asks=None` = illimité,
`max_asks=0` = questions interdites ; `timeout_s=None` = attente infinie, `timeout_s<=0` = timeout immédiat ;
`remaining` vaut `-1` quand `max_asks=None`.

`Mail`, non exporté mais présent dans les valeurs de retour, est une dataclass avec les champs
`id` / `text` / `sent_at` / `taken`.

---

## Lignage {#血缘}

Source : [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Enregistre, entre processus, quelle étape a utilisé quelle session ; c'est grâce à lui que la
[continuité](glossary.md#接续) retrouve où le run précédent s'est arrêté. Le fichier est `<run_dir>/lineage.json`.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `path` | `Path` | obligatoire | chemin du fichier de lignage |
| `workspace` | `Path` | obligatoire | espace de travail. `__post_init__` le résout |
| `steps` | `dict[str, str]` | `{}` | nom d'étape → `session_id` |
| `woke` | `int` | `0` | nombre de réveils |

| Membre | Signature | Description |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lit `<run_dir>/lineage.json`. **Fichier absent, illisible, ou champ `workspace` qui ne correspond pas : renvoie un lignage vide, sans erreur** |
| `remember` | `(step: str, session_id: str) -> None` | mémorise l'association et **écrit immédiatement sur disque**. Retourne directement si step ou sid est vide |
| `bump` | `() -> int` | incrémente le compteur de réveils, écrit sur disque, renvoie la nouvelle valeur (`1` au premier run) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **déplace** le fichier de lignage + `extra` dans `<into>/<YYYYmmdd-HHMMSS>/`, et remet `steps` / `woke` à zéro. **Déplacement, pas suppression** |

L'écriture sur disque passe par un remplacement atomique `tmp.replace(path)` ; les `OSError` sont avalées
silencieusement — un échec d'écriture ne doit pas emporter le run.

**`workspace` est un garde-fou** : la `project_key` du SDK est dérivée du chemin de l'espace de travail ;
si le répertoire a été copié ailleurs, les anciens `session_id` sont introuvables, donc un chemin qui ne
correspond pas équivaut à pas de lignage.

Quand `Workflow.run` charge le lignage, il vérifie chaque enregistrement un par un avec
`runtime.has_session(sid)` pour voir s'il est encore en base, et ne l'utilise que s'il est vivant —
le fichier de lignage peut survivre à `sessions.db`.

---

## Exemples minimaux utilisables {#示例}

Les cinq extraits tournent directement. Prérequis : `claude-agent-sdk` installé, `ANTHROPIC_API_KEY` ou
`ANTHROPIC_AUTH_TOKEN` disponible (sinon `Runtime(...)` lève un `RuntimeError` dès la construction).

### Un agent, une étape {#示例-单-agent}

Squelette minimal : déclarer un `AgentSpec`, créer un `Runtime`, `await rt.run(...)`, lire le `StepResult`.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Les paramètres de `Runtime` sont **tous keyword-only** ; `spec` et `prompt` de `rt.run()` sont positionnels,
le reste est keyword-only. `AgentSpec` a par défaut `allowed_tools=["Read", "Glob", "Grep"]` et
`delegate_only=False`, donc `Runtime` lui installe automatiquement [`whitelist_guard`](#whitelist-guard),
qui bloque `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordinateur + worker {#示例-协调}

Un [coordinateur](glossary.md#协调者) qui ne met pas la main à la pâte, avec un [worker](glossary.md#执行者)
qui travaille. C'est la première couche d'économie de contexte de flower.

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True est obligatoire : delegate_guard est accroché dans workbench_hooks,
    # sans workbench, les Bash/Write du coordinateur ne sont interceptés par aucun hook.
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Les deux premiers paramètres de `worker()` sont positionnels : `description` (ce sur quoi le coordinateur
choisit qui appeler) et `prompt` (son system prompt, auquel `WORKER_RULES` est concaténé automatiquement).
Les trois premiers de `coordinator()` sont positionnels : `name`, `instructions`, `workers`.

### Écrire son propre Workflow {#示例-workflow}

Deux étapes, la seconde injectant le résultat de la première dans son propre prompt — bon marché, isolé,
sans session partagée.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # Nouvelle session : ne consomme que ce qui est dans le prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Nouvelle session + résultat de l'étape précédente injecté dans le prompt (bon marché, anti-pollution)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Pour continuer dans la même session, écrire resume_from="造句" ; pour bifurquer, ajouter fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (quand reduce n'est pas fourni)
    print(ctx["_sessions"])            # nom d'étape -> session_id
    print(ctx.get("_failed_at"))       # avec on_fail="stop", à quelle étape ça a échoué


asyncio.run(main())
```

Les trois premiers champs de `Step` (`name` / `spec` / `prompt`) sont positionnels, et `steps` de `Workflow`
aussi. `Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positionnel, les deux callbacks
keyword-only. **Attention, `continuous=True` est la valeur par défaut** : au deuxième run avec le même
`run_dir` et le même `workspace`, même les étapes dont `resume_from=None` reprennent la session précédente.

### Ajouter une garde d'objectif {#示例-目标}

D'abord laisser le [juge](glossary.md#判定者) fixer l'objectif et les critères de verdict, puis faire accepter
le verdict par l'étape de travail — si le verdict ne passe pas, on recommence avec le retour, trois tours au maximum.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = tout automatique : toute question tombe à vide immédiatement, on ne fait pas semblant d'attendre
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds est le **nombre total de tours** : rounds=3 → retries=2 → au plus trois tours de travail
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # Le prompt de goal_step lit ctx["确认需求"] (valeur par défaut de brief_key).
        # Sans clarify_step, il faut en injecter un soi-même, sinon il ne verra que "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY : l'objet Goal
    print(ctx["_verdict"])     # VERDICT_KEY : le dernier Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY : nombre de tours effectués
    print(ctx.get("_aborted")) # la raison du StepAbort (objectif inatteignable et personne ne répond)


asyncio.run(main())
```

`with_goal` ne remplace que `gate` / `on_reject` / `retries` ; les autres champs sont repris tels quels via
`dataclasses.replace`. Le juge est une **session indépendante** : `gate` appelle en interne
`rt.run(judger, ..., step_name=f"{label}#{轮次}")`, avec `resume` toujours à `None`.

### Remplacer la couche d'interaction {#示例-交互层}

Pour passer du terminal à du Web / TUI / HTTP, il n'y a que deux choses à changer : la fonction qui rend les
`Event`, et la coroutine qui récupère les questions.

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
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # Les kind == "ask" qui ne sont pas des mail sont traités par answerer ci-dessous (mode pull)


async def answerer(ch: HumanChannel) -> None:
    """Récupération des questions en mode pull. Pour un backend Web / service HTTP, c'est la seule coroutine à changer."""
    while True:
        ask = await ch.next_ask()          # sans timeout, attend indéfiniment
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Le Runtime utilise le workbench déjà construit par le workflow — n'en fabriquez pas un autre
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push et pull : **choisissez-en un**. Le push, c'est construire `HumanChannel(on_event=...)` ; le pull, c'est
`await channel.next_ask()`. `Workflow.run` ne câble automatiquement que si `channel.on_event is None`, donc si
vous avez fourni `on_event` vous-même il ne sera pas écrasé.
`answer()` / `decline()` / `send()` / `interrupt()` **sont tous appelables depuis un autre thread**.

---

## Pièges et erreurs fréquentes {#陷阱}

Classés dans l'ordre où on les rencontre, pas par module. Chaque point vient d'une observation réelle.

### Assemblage {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = pas le moindre garde-fou sur le thread principal.**
   `delegate_guard` n'est installé que s'il y a un workbench, et `whitelist_guard` est court-circuité par
   `delegate_only=True`. Si vous utilisez un coordinateur, activez le workbench. Voir [Runtime](#runtime).
2. **Il y a deux emplacements de workbench, ne vous trompez pas de chemin.** `Runtime(workbench=True)` tombe
   dans `<run_dir>/workbench` ; `Workbench(ws)` vaut par défaut `<ws>/.flower`. Quand vous construisez
   `brief_path` à la main, suivez le second, sinon **le brief est écrit dans le répertoire A pendant que
   l'index injecté scanne le répertoire B, et rien ne signale l'erreur**.
   La bonne pratique : le workflow fait lui-même `Workbench(...).ensure()`, l'accroche à `Workflow.workbench`,
   puis passe **le même objet** à `Runtime(workbench=wb)`.
3. **`allowed_tools` n'est pas une liste blanche exclusive, c'est une liste de dispense d'approbation.**
   Le modèle peut toujours appeler des outils qui n'y figurent pas. Le fait que `clarify()` / `judge()`
   « n'aient pas d'outil d'écriture » repose sur le hook [`whitelist_guard`](#whitelist-guard).
   Et `coordinator()` a par défaut `permission_mode="acceptEdits"` — quiconque passe cette valeur à
   `clarify()` / `judge()` fait sauter la protection.
4. **`disallowed_tools` est au niveau de la session** : il désactive aussi les outils du même nom chez les subagents.
5. **L'index du workbench n'atteint pas les subagents.** « Les productions longues vont dans `artifacts/` » doit
   être relayé par le coordinateur dans le task brief, c'est le seul canal.
6. **`Runtime(...)` lève un `RuntimeError` dès la construction** en l'absence d'identifiants, pas au moment de `run()`.
7. **`Runtime.run_id` doit être unique par instance.** `manifest.json` déduplique sur le champ `run` ; si deux id
   entrent en collision, celui qui écrit en dernier prend les lignes de l'autre pour « ce qu'il a écrit la fois
   précédente » et les supprime.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` est la valeur par défaut**, `resume_from=None` ne signifie pas « session neuve ».
   Pour repartir de zéro à chaque fois, mettez explicitement `continuous=False`.
   **Changer le nom d'une étape revient à couper le lignage.**
9. **`with_goal(rounds=N)` est le nombre total de tours, pas le nombre de tours supplémentaires** :
   `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` n'écrit pas `ctx[step.name]`** — un `lambda ctx: ctx["某步"]` en aval lèvera un `KeyError`.
    Pour continuer avec un résultat incomplet, utilisez `on_fail="continue"`.
11. **Un `resume_from` pointant vers une étape non exécutée ou en échec lève un `ValueError`**, il n'est pas ignoré silencieusement.
12. **`Step.reduce` doit être une fonction synchrone ; `gate` / `when` / `on_reject` peuvent être async.**
13. **`fork=True` sans `resume` est silencieusement sans effet.** `Workflow` ne passe jamais `resume_at` ;
    pour revenir en arrière au message près, il faut appeler `Runtime.run` directement.
14. **Quand vous pilotez `Runtime` vous-même, `on_session` doit être retiré avant le gate**, sinon la session du
    juge sera inscrite dans le lignage de l'étape de travail. `Workflow` le garantit avec un `try/finally`.
15. **`step_name` détermine la clé dans le manifeste et le lignage.** `Workflow` ajoute des suffixes
    `#retryN` / `#roundN`, le juge ajoute `#轮次` — **les noms suffixés n'entrent pas dans le lignage
    inter-processus**, c'est précisément l'une des façons dont « le juge est toujours une nouvelle session » est implémenté.

### Rôles {#陷阱-角色}

16. **`clarify(max_turns=<petit nombre>)` réduit à néant le « nombre de questions illimité »** — chaque question consomme un tour.
17. **`goal_step()` n'a pas de paramètre `can_run`**, il faut passer `can_run=True` via `**spec_kw`.
    Sans cela, le juge qui fixe l'objectif n'a pas `Bash`, et la règle de `JUDGE_RULES` « commence par bien voir
    dans quel environnement tu es » ne peut pas s'exécuter.
18. **`judge(can_run=True)` permet au juge de modifier l'espace de travail** — `whitelist_guard` est dérivé de
    `allowed_tools`, donner `Bash` laisse passer `Bash` (`Write`/`Edit` restent bloqués, mais `Bash` lui-même
    peut écrire des fichiers). Pour une neutralité absolue, ne l'activez pas.
19. **`worker(isolate=True)` exige que le workspace soit un dépôt git**, sinon l'outil `Agent` renvoie
    directement `"not in a git repository"`, sans dégradation silencieuse. Et le marqueur d'isolation est un
    attribut Python : **faire un `dataclasses.replace()` sur un `AgentDefinition` le perd**.
20. **Quand vous construisez un `AgentDefinition` directement, les paramètres sont en camelCase** :
    `maxTurns`, `permissionMode`. `worker()` fait déjà la conversion pour vous.

### Handoff et contexte {#陷阱-换代}

21. **Quand le handoff est activé, l'auto-compact est forcé à off, sans filet.** L'étape qui rédige le document
    de handoff doit donc avoir un chemin de dégradation. Pour conserver l'auto-compact, fournissez explicitement
    `AgentSpec.compact`.
22. **Un `HandoffPolicy.window` trop petit provoque des handoffs infinis qui brûlent de l'argent.** Le seul frein
    est `max_generations=8`. À l'autre extrémité, **`default_window()` renvoie aussi `1_000_000` quand aucune des
    deux variables d'environnement n'est définie** — une estimation trop grande est rattrapée par `is_overflow()`
    (qui la transforme en un handoff dégradé), ce n'est pas une erreur dure, mais le handoff de cette génération
    est dégradé.
23. **Sans workbench, le handoff n'est pas écrit sur disque.** Le document est quand même transmis au successeur
    via le prompt, mais l'humain ne peut pas le retrouver après coup.

### Stockage {#陷阱-存储}

24. **`Runtime(trim=False)` (le défaut) ne veut pas dire « on ne nettoie rien ».** Le store est toujours un
    `PruningSessionStore` ; `trim=False` ne désactive que le trim des gros résultats ; **le retrait des résidus
    de déconnexion, le retrait des appels refusés, la neutralisation des restes d'interruption et l'expiration
    temporelle continuent.**
25. **Les deux répertoires de spill ne sont pas le même** : `spill_guard` écrit dans `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` écrit dans `<workspace>/.flower/spill/` (obligatoirement dans l'espace de travail).
26. **Le quatrième paramètre positionnel de `PruningSessionStore.__init__` est `prune`, pas `ephemeral`**,
    contrairement à la classe parente. Passer par position décale silencieusement les arguments.

### Documents et interaction {#陷阱-文书}

27. **Quand `Verdict` n'arrive pas à extraire de conclusion, `state=""` et `ok=False` ; à ne jamais interpréter
    comme un objectif atteint.**
    Par ailleurs « 无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable » sont tous rangés dans `unreachable`,
    ce qui déclenche la voie « on s'arrête et on demande à l'humain », pas « on refait un tour ».
28. **`Brief.parse` rejette tout ce qui suit une clôture de bloc de code manquante** — quand la sortie du modèle
    est tronquée, aucune des sections suivantes n'est parsée, `complete()` vaut `False`, et le gate renvoie
    l'étape en arrière.
29. **`Brief.load` traite `"(未填)"` comme vide.** Si vous éditez le brief à la main en recopiant le texte
    d'espace réservé, la section compte toujours comme manquante.
30. **Les trois sémantiques « 0 / None » de `HumanChannel` sont toutes différentes** : `max_asks=None` illimité,
    `max_asks=0` questions interdites ; `timeout_s=None` attente infinie, `timeout_s<=0` timeout immédiat ;
    `remaining` renvoie **`-1`** quand `max_asks=None`.
31. **`Event("ask")` porte à la fois les questions et ce que l'humain dit de lui-même**, ce dernier avec
    `payload["kind"] == "mail"`. L'UI doit d'abord le tester.
32. **`Workflow.run` ne câble automatiquement que si `channel.on_event is None`** —
    si vous construisez `HumanChannel(on_event=...)` vous-même, les événements de question n'iront pas
    simultanément dans la sortie `on_event` du workflow.
