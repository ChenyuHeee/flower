# API Python

Cette page épuise les **62 symboles publics** du `__all__` de premier niveau de `flower` : signatures, paramètres, valeurs par défaut, sémantique,
attributs et méthodes publics. Après lecture, plus besoin d'ouvrir les sources pour retrouver un paramètre.

L'organisation suit **ce qui vous préoccupe**, pas le découpage en fichiers de modules — pour savoir « comment empêcher le [coordinateur](glossary.md#协调者)
de mettre lui-même la main à la pâte », allez à la [couche hook](#hook) ; pour savoir « comment le résultat de l'étape précédente arrive à la suivante », allez au [workflow](#流程).
La terminologie suit uniformément le [glossaire](glossary.md).

Version `0.1.0`, dépend de `claude-agent-sdk>=0.2.152`. Toutes les signatures correspondent mot pour mot aux sources.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## Ce que contient cette page {#索引}

| Sujet | Symboles |
|---|---|
| [Lancer un agent](#运行时) | `Runtime` `StepResult` |
| [Enchaîner plusieurs étapes](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Fabriquer un rôle](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Écrire une définition d'agent à la main](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documents structurés](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Intercepter des outils, tailler des résultats, isoler](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Le répertoire de travail du spill](#工作台) | `Workbench` |
| [Comment et quoi stocker des sessions](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Que faire en cas de coupure réseau](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Remplacer l'UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Reprendre la fois précédente entre processus](#血缘) | `Lineage` |

## Six valeurs par défaut qui mordent {#危险默认值}

Ces six lignes ne sont pas des détails : ce sont les six accidents les plus fréquents. Chacune est expliquée intégralement dans la section correspondante.

| Valeur par défaut | Conséquence | Détail |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | Les `Bash`/`Write`/`Edit` du main thread n'ont **aucun hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Impose au spec une `CompactPolicy(mode="no_summary")`, soit `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Une étape avec `resume_from=None` reprend quand même la session précédente entre processus | [Workflow](#workflow) |
| `build_options(fork=True)` sans `resume` | Échoue silencieusement, sans erreur | [build_options](#build-options) |
| `clarify(max_turns=<petit nombre>)` | Transforme « poser des questions sans limite » en promesse creuse — chaque question est un tour | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Portée session : interdit aussi aux subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Sources : [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` est le cœur d'exécution. Il détient l'espace de travail, le [session store](glossary.md#会话存储), le [workbench](glossary.md#工作台),
la politique de [résilience](glossary.md#韧性) et la politique de [handoff](glossary.md#换代), et n'expose qu'un seul verbe : `run` une étape.
Les reprises, la poursuite après interruption, le handoff quand le contexte est plein — tout se fait dans cet unique appel.

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

Les paramètres de construction sont **tous keyword-only** (`*` en tête), `workspace` est obligatoire.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | obligatoire | Le `cwd` de l'agent. Resolve à la construction puis `mkdir(parents=True, exist_ok=True)`. La `project_key` du SDK en est dérivée — si le répertoire est déplacé, les anciens `session_id` deviennent introuvables |
| `run_dir` | `str \| Path` | `"runs"` | Contient `sessions.db`, `manifest.json`, `lineage.json`, ainsi que le workbench par défaut quand `workbench=True`. Également resolve puis mkdir |
| `portable` | `bool` | `True` | Transmis à `build_options(portable=)`, soit `setting_sources=[]` : ne lit ni le `~/.claude/` de la machine hôte, ni le `.claude/` du projet. Voir [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Une instance est utilisée telle quelle ; un `bool` donne `TrimPolicy(enabled=bool(trim))`. **Désactiver signifie seulement ne pas tailler les gros résultats ; le prune se fait quand même** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Même règle de conversion. Va de pair avec `coordinator(glance=True)` — si vous laissez le main thread lancer `git status`, il faut garantir que ce résultat expire |
| `keep_denials` | `int` | `1` | Transmis à `PrunePolicy(keep_denials=)`. Conserve les N derniers appels d'outil refusés ; les plus anciens sont retirés, appel et résultat compris |
| `workbench` | `Workbench \| bool` | `False` | Une instance est utilisée telle quelle ; `True` crée `Workbench(workspace, home=run_dir / "workbench")` (**par défaut hors de l'espace de travail**). Suivi immédiatement d'un `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | À partir de combien de caractères un résultat d'outil part en [spill](glossary.md#落盘). `None` ou `0` = pas de `spill_guard` installé |
| `resilience` | `Resilience \| bool` | `True` | Même règle de conversion |
| `handoff` | `HandoffPolicy \| bool` | `True` | Même règle de conversion |

**Le session store est figé en dur** : c'est toujours
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Les paramètres de construction **n'offrent pas** de point d'entrée pour changer de backend — pour en changer, construisez vous-même `AgentSpec` + `build_options(session_store=...)`,
ou écrasez `rt.store` après construction.

Les deux dernières étapes de la construction sont `load_dotenv()` et `check_credentials()`, et **la seconde lève `RuntimeError` en cas d'erreur**.
Sans identifiants, ça explose à la construction, pas au `run()`.

!!! warning "`workbench=False` + `coordinator()` = aucun mur devant le main thread"
    `delegate_guard` n'est installé que dans `workbench_hooks`, et `workbench_hooks` n'est appelé que si `self.workbench is not None` ;
    `whitelist_guard`, lui, est court-circuité par `if not spec.delegate_only`. Or `coordinator()` pose systématiquement
    `delegate_only=True` et, par défaut, `glance=True` donne accès à `Bash`.

    **Conclusion : avec un coordinateur configuré en `Runtime(workbench=False)`, ses `Bash`/`Write`/`Edit` ne sont interceptés par aucun hook.**
    Si vous utilisez `coordinator()`, activez le `workbench` — `Runtime(..., workbench=True)` ou passez une
    instance de `Workbench`.

!!! warning "`handoff=True` (défaut) désactive de force l'auto-compact"
    Dans `_attempt` : `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    ce qui donne `DISABLE_AUTO_COMPACT=1` dans le sous-processus. La raison : avec les deux mécanismes actifs en même temps, on ne peut plus dire qui a fait retomber le contexte.

    **Le prix : l'étape qui écrit le handoff doit avoir un chemin dégradé** (`handoff.degraded`), puisqu'il n'y a plus de compact en filet.
    Pour conserver l'auto-compact, fournissez explicitement `AgentSpec.compact` (si le spec le fournit, il est respecté, pas écrasé).

#### Attributs publics {#runtime-属性}

| Attribut | Type | Description |
|---|---|---|
| `workspace` | `Path` | L'espace de travail après resolve |
| `run_dir` | `Path` | Le répertoire de run après resolve |
| `portable` | `bool` | Conservé tel quel |
| `store` | `PruningSessionStore` | Le session store. Changer de backend n'est possible qu'en l'écrasant après construction |
| `resilience` | `Resilience` | L'instance normalisée |
| `handoff` | `HandoffPolicy` | L'instance normalisée |
| `workbench` | `Workbench \| None` | `None` quand `workbench=False` |
| `spill_threshold` | `int \| None` | Conservé tel quel, transmis à `workbench_hooks` dans `_attempt` |
| `results` | `list[StepResult]` | Chaque étape exécutée dans ce processus, ajoutée dans l'ordre |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Doit être unique par instance** — `manifest.json` déduplique sur le champ `run` ; en cas de collision d'id, la dernière écriture prend les lignes de l'autre pour les siennes et les supprime |
| `on_session` | `Callable[[str], None] \| None` | Rappelé **immédiatement** à l'obtention d'un nouveau `session_id`, `None` par défaut. **Ne doit couvrir que l'appel `runtime.run`** — le [juge](glossary.md#判定者) utilise le même `Runtime`, et le laisser branché pendant le gate écrirait la session du juge dans la [lignée](glossary.md#血缘) de l'étape de travail |

Constantes de classe : `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (le paragraphe ajouté après les mots de l'humain lors de la reprise après interruption, expliquant que « les appels d'outil en vol qui renvoient interrupted
sont un effet de bord normal de l'interruption, pas une panne d'environnement »).

#### Méthodes publiques {#runtime-方法}

| Méthode | Signature | Description |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Exécute une étape. Voir ci-dessous |
| `interrupt` | `(message: str = "") -> None` | Demande l'interruption du tour en cours. **Appelable depuis n'importe quel thread**. Coopératif : coupure propre à la **frontière d'un message**, pas d'annulation dure. Chaîne vide = interrompre sans rien dire |
| `rescue` | `() -> None` | Solde les comptes autant que possible avant d'être tué de force, appelé par les handlers `SIGHUP`/`SIGTERM`. L'étape en vol est également écrite dans le manifest, avec `error="killed-by-signal"`. N'effectue que de petites écritures synchrones |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | Dans `str(workspace.resolve())`, `/`, `_` et `.` sont tous remplacés par `-`. **Dérivée du cwd par le SDK, l'appelant ne peut pas la fixer** |
| `has_session` | `(session_id: str) -> bool` | Cet id est-il encore trouvable dans **cet espace de travail** ? Synchrone, ne lit pas le payload |
| `context_of` | `(session_id: str) -> int` | La taille de contexte au dernier tour d'une session donnée, délégué à `store.last_context` |
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
| `step_name` | `str \| None` | `None` | La clé posée dans `StepResult.step`, le manifest et la lignée. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Reprend ce `session_id` |
| `fork` | `bool` | `False` | Bifurque vers une nouvelle session sans polluer l'originale. **N'a d'effet que si `resume` est vrai** |
| `resume_at` | `str \| None` | `None` | Reprend à partir d'un message donné (rollback). Là encore, **n'a d'effet que si `resume` est vrai** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie des événements, voir [`Event`](#event) |

Au début de chaque étape, le niveau de contexte est remis à zéro (`self._ctx, self._warned = 0, False`). Suit une boucle, avec quatre sorties :

1. **Succès** → on sort.
2. **Interruption humaine** (`result.error == INTERRUPTED`) → **non soumis à `max_attempts`**, n'attend pas le réseau.
   `resume` sur la même session avec les mots de l'humain, `attempt -= 1` (une interruption ne compte pas comme tentative ratée), prompt = mots de l'humain + `INTERRUPT_NOTE`.
   **Sans `session_id` obtenu, il n'y a plus qu'à s'arrêter.**
3. **Contexte plein** (`result.error == HANDOFF_DUE`, ou `handoff.enabled` avec un `session_id` obtenu et
   `is_overflow(...)` qui déclenche) → **également non soumis à `max_attempts`**. On vérifie d'abord `len(result.retired) >= handoff.max_generations` ;
   si dépassé, l'erreur est remplacée par un diagnostic et on sort ; sinon on écrit le [document de handoff](glossary.md#交接书) → `resume=None, fork=False`
   (**session entièrement neuve**) → le prompt devient `h.prompt_block()` → niveau de contexte remis à zéro → `attempt -= 1`.
4. **Panne réanalysable** → on sort si `not resilience.enabled or attempt >= max_attempts` ;
   on sort aussi si `classify(error)` juge qu'il ne faut pas réessayer ; sinon on émet `Event("retry")`, on attend le réseau avec `wait_online()`,
   puis `sleep(delay_for(attempt))` ; **si un `session_id` a été obtenu, on reprend avec `resume`** (le prompt devient
   `resilience.resume_prompt`), et `result.resumed` passe à `True`.

Pour finir : écriture de `ended_at`, ajout à `self.results`, écriture de `manifest.json`.

`manifest.json` a une sémantique d'**append** : chaque écriture relit le disque et déduplique sur le champ `run` (ses propres lignes sont remplacées, celles des autres conservées),
donc lancer deux flower en parallèle sur le même `run_dir` est sûr — à condition que les `run_id` ne collisionnent pas.

**Les trois points d'observation du handoff** (tous des `Event("handoff")`, distingués par `payload["phase"]`) :
`near` (approche de `warn_at`, émis une seule fois par génération), `writing` (le handoff est en cours d'écriture, une dizaine de secondes),
`done` (payload avec `degraded` / `path` / `sections`). Le tour qui écrit le handoff s'exécute avec
`replace(spec, max_budget_usd=None)` — le handoff doit pouvoir s'écrire, il ne peut pas rester bloqué sur le budget ;
et `on_event=None`, ce tour ne remonte rien à l'UI.

Le handoff est écrit dans `<workbench.notes>/交接-<步骤名>.md` ; **sans workbench, pas d'écriture sur disque**, le document passe quand même au successeur via le prompt,
il est simplement introuvable après coup. Les anciens handoffs sont déplacés dans `notes/archive/交接/<名>-<时间戳>.md`.

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
| `session_id` | `str \| None` | `None` | **Toujours la dernière session à avoir pris le relais** — celles brûlées par un handoff en cours de route sont dans `retired` |
| `ok` | `bool` | `False` | L'étape a-t-elle réussi |
| `cost_usd` | `float` | `0.0` | En dollars. **Cumulé** à travers les reprises et les handoffs |
| `num_turns` | `int` | `0` | Nombre de tours, également cumulé |
| `text` | `str` | `""` | **Contient uniquement le corps du main thread.** Les propos d'un subagent restent dans son propre transcript, et la task brief qui lui est confiée est `kind="prompt"` ; ni l'un ni l'autre n'entrent ici |
| `error` | `str \| None` | `None` | Raison de l'échec. Valeurs spéciales : voir `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Nombre réel de tentatives. Les interruptions et les handoffs **ne comptent pas** |
| `errors` | `list[str]` | `[]` | Messages d'erreur API synthétiques collectés, **n'entrent pas dans `text`** |
| `resumed` | `bool` | `False` | Y a-t-il eu une reprise par resume en cours de route |
| `retired` | `list[str]` | `[]` | Les `session_id` brûlés par les handoffs de cette étape, dans l'ordre |
| `context` | `int` | `0` | La taille de contexte réellement vue par le main thread au dernier tour, c'est-à-dire le critère de handoff |

| Attribut | Type | Description |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, `0.0` si non terminé |

---

## Workflow {#流程}

Source : [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Un [workflow](glossary.md#流程) est un ensemble de [steps](glossary.md#步骤) enchaînés dans l'ordre, plus la manière dont l'état circule entre eux et le moment où l'on sort par anticipation. **Le framework ne fournit aucun workflow tout fait, le workflow c'est vous qui l'écrivez** — `starter_flow` n'est qu'un gabarit qui tourne.

Alias de type `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, présent dans `flower.workflow.__all__`, pas dans le `__all__` de premier niveau).

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

La **déclaration** d'un step. `Step` n'est pas lui-même une fonction — ce qui s'exécute réellement, c'est `Runtime.run(step.spec, prompt, ...)`. Les trois premiers champs sont positionnels, `Step("取词", terse, "读 seed.txt …")` est une écriture valide.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du step. **Clé stable d'un processus à l'autre** — elle atterrit dans `ctx[name]`, `ctx["_results"]`, le manifest et le lineage. Renommer = casser le lineage |
| `spec` | `AgentSpec` | requis | Quel agent exécuter |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | Ce qu'on dit. Peut être une closure qui calcule à partir de `ctx` |
| `resume_from` | `str \| None` | `None` | La session de quel step reprendre. Si le step visé n'a produit aucune session, **lève une `ValueError`**, ce n'est pas un saut silencieux |
| `fork` | `bool` | `False` | Forker à partir de `resume_from`. **Sans `resume_from`, sans effet** |
| `retries` | `int` | `0` | Nombre de tentatives supplémentaires quand la gate ne passe pas. `retries=0` = une seule passe |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Juge si cette passe est acceptée. **Peut être async.** Retourner `False` vaut échec. **Appelée une seule fois par tentative** — elle peut avoir des effets de bord (par exemple écrire le brief sur disque) et ne doit pas être déclenchée en double |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, voir plus bas |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Retourner `False` **saute le step entier** : aucun result produit, rien dans `ctx["_results"]`. **Peut être async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **Ce qu'on dit à la passe suivante** quand la gate ne passe pas. **Peut être async.** Le fournir change la sémantique du retry, voir plus bas |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Le prompt utilisé en continuité (plutôt qu'un redémarrage depuis zéro) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Décide ce que contient `ctx[name]`. Par défaut le `result.text` brut. **Doit être une fonction synchrone** |

| Méthode | Signature | Description |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Si `resuming` et qu'un `resume_prompt` existe, utilise ce dernier, sinon `prompt` ; si c'est un callable, l'appelle avec `ctx` |

**Trois façons de raccorder les sessions** (au sein d'un même run) :

| Écriture | Effet |
|---|---|
| `resume_from=None` (défaut) | Nouvelle session, uniquement le contexte passé dans le prompt. Bon marché, isolé. **Mais avec `Workflow(continuous=True)`, la session du step de même nom est reprise depuis le lineage inter-processus** |
| `resume_from="nom du step précédent"` | Reprend la même session, contexte complet. Cher, cohérent |
| `resume_from="nom du step précédent", fork=True` | Fork, sans polluer la session d'origine. Pour la relecture / des variantes en parallèle |

**`on_reject` change la sémantique du retry** :

- Non fourni → la tentative suivante **repart de zéro** (même prompt, même `resume_from`).
- Fourni → la tentative suivante **reprend la session qui vient d'être rejetée**, le prompt devient sa valeur de retour, `fork` est forcé à `False`.
- Retourne une chaîne vide → pas de renvoi, on retombe sur un redémarrage depuis zéro.
- `result.session_id` vaut `None` → on retombe aussi sur un redémarrage depuis zéro.

**Les trois valeurs de `on_fail`** :

| Valeur | Comportement |
|---|---|
| `"stop"` (défaut) | Écrit `ctx["_failed_at"] = name`, **interrompt tout le workflow** |
| `"skip"` | Passe au step suivant, **`ctx[name]` n'est pas écrit** — en aval, `lambda ctx: ctx["某步"]` lèvera un `KeyError` |
| `"continue"` | `ctx[name] = result.text`, on continue avec un résultat incomplet |

Que la gate passe ou non, `ctx["_results"][name] = result` est toujours écrit ; si `result.session_id` est non vide, il est aussi écrit dans `ctx["_sessions"]` avec `lineage.remember(...)`.

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

Exécute une suite de `Step` dans l'ordre et retourne le `ctx` final. `steps` est positionnel, `Workflow([...])` est valide.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `steps` | `list[Step]` | requis | Exécutés dans l'ordre |
| `name` | `str` | `"workflow"` | Nom du workflow |
| `context` | `Ctx` | `{}` | Dictionnaire de contexte initial. **Au deuxième run d'un même `Workflow`, c'est le même dict** |
| `channel` | `HumanChannel \| None` | `None` | À brancher ici quand il faut s'arrêter pour demander à un humain. `run()` raccorde automatiquement son `on_event` à la même sortie, **uniquement si `channel.on_event is None`** ; c'est aussi par ce champ que le programme pilote sait à qui répondre |
| `workbench` | `Workbench \| None` | `None` | Le workbench désigné par le workflow, pour que le programme pilote le retrouve |
| `continuous` | `bool` | `True` | Même chemin = même conversation. Implémenté par [`Lineage`](#lineage) |

| Paramètre de `run()` | Type | Défaut | Description |
|---|---|---|---|
| `runtime` | `Runtime` | requis, positionnel | Avec quel runtime exécuter |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie d'events, transmise telle quelle à chaque `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Rappelée une fois à la fin de chaque step |

!!! warning "`continuous=True` est la valeur par défaut, `resume_from=None` ne veut pas dire session neuve"
    Quand la continuité est active, `run()` appelle d'abord `Lineage.open(run_dir, workspace)`, puis vérifie chaque enregistrement avec `runtime.has_session(sid)` pour savoir s'il est encore en base ; seuls les vivants sont injectés dans `ctx["_sessions"]`. Résultat : **un step avec `resume_from=None` continue lui aussi la session précédente** — y compris après un process tué ou un redémarrage machine.

    Pour avoir une session neuve à chaque fois, écrivez explicitement `Workflow(..., continuous=False)`.
    Par ailleurs : **le nom du step est une clé stable d'un processus à l'autre, le changer revient à couper le lineage.**

Les **clés privées** que `run()` écrit dans le ctx (toutes préfixées par `_`, aucune collision possible avec un nom de step) :

| Clé | Contenu |
|---|---|
| `_runtime` | Le `Runtime` reçu. **C'est par lui qu'une gate lance un agent** |
| `_on_event` | La sortie d'events. L'agent lancé dans une gate doit lui aussi pouvoir atteindre l'UI, sinon l'écran reste noir |
| `_sessions` | `dict[nom de step, session_id]`, lu avec `setdefault` |
| `_results` | `dict[nom de step, StepResult]` |
| `_lineage` | L'objet `Lineage`. Présent uniquement si `continuous=True` et que le runtime a un `run_dir` + un `workspace` |
| `_woke` | La valeur retournée par `lineage.bump()`, le numéro de ce réveil |
| `_aborted` | Le message du `StepAbort` |
| `_failed_at` | Le nom du step en échec quand `on_fail="stop"` |

Payload d'`Event("step")` : `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Étiquettes de retry** : la passe 0 utilise `step.name` ; ensuite, avec `on_reject`, `f"{name}#round{attempt+1}"`, sinon `f"{name}#retry{attempt}"`. Dans le manifest on voit d'un coup d'œil comment ce step s'est terminé. **Les noms suffixés n'entrent pas dans le lineage inter-processus** — `Lineage.remember` utilise le nom d'origine.

`runtime.on_session` ne couvre que l'instruction `runtime.run`, avec un `try/finally` qui garantit son retrait avant la gate. `prompt_cur` / `resume_cur` / `fork_cur` sont des variables locales, jamais réécrites dans `step` — le même objet `Step` peut être exécuté une deuxième fois.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Levée par une `gate` = **arrêt immédiat, ne pas réessayer**. La différence avec « retourner `False` » : `False` signifie « pas cette fois, on refait une passe » ; `StepAbort` signifie « refaire ne servira à rien ».

Après la levée : `ctx["_aborted"] = str(exc)`, `passed = False`, **sortie de la boucle de retry (les `retries` restants ne sont pas consommés)**, puis traitement comme un échec ordinaire via `on_fail` (par défaut `"stop"`).

`with_goal` la lève à deux endroits : quand `ctx["_runtime"]` est introuvable, et quand le verdict est `unreachable` sans que personne ne réponde.

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

Produit un `Step` de [clarify](glossary.md#前置确认) : cerner le besoin → parser en [`Brief`](#brief) → geler et écrire sur disque dès que les quatre sections sont complètes.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Canal de questions |
| `brief_path` | `str \| Path` | requis | Où atterrit le [brief](glossary.md#需求确认书). **Doit atterrir dans le workbench réellement injecté dans l'index** |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | La demande brute de l'humain |
| `name` | `str` | `"确认需求"` | Nom du step, et en même temps clé dans `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Si absent, utilise `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions supplémentaires ajoutées au [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = redemander à chaque fois, que le brief existe ou non |
| `on_fail` | `str` | `"stop"` | Comme `Step.on_fail` |
| `retries` | `int` | `0` | Nombre de relances quand les quatre sections ne sont pas réunies |
| `**spec_kw` | | | Transmis tel quel à [`clarify()`](#clarify-role), donc on peut écrire `can_read=False`, `max_budget_usd=...` |

Voici comment sont remplis les champs du `Step` produit :

- `resume_prompt = CLARIFY_RESUME`.
- `when` : `always_ask=True` → toujours `True` ; sinon, si `Brief.load(brief_path)` est complet, l'injecte dans le ctx **puis retourne `False` (saut)** — il faut injecter même en sautant, sinon l'aval n'a pas le besoin.
- `gate` : `Brief.parse(result.text)` ; incomplet → écrit `ctx[MISSING_KEY]` et retourne `False` ; complet → `b.write(brief_path)` pour geler, injecte dans le ctx, retourne `True`.
- `reduce` : retourne `ctx[BRIEF_KEY].prompt_block()`, **pas le texte brut du modèle** — le brut peut contenir ce qu'il a écrit en plus.
- `resume_from` **reste à `None` par défaut** : le step suivant est une nouvelle session, il reçoit le brief mais pas les questions-réponses. Ces échanges de clarify **ne sont jamais entrés** dans le contexte du coordinator, ils n'y ont pas été taillés après coup.

Les trois injections dans le ctx : `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Constante | Valeur | Description |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` est un objet `Brief` ; `ctx[step.name]` est son `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Les sections manquantes en cas d'échec de clarify (noms de section en chinois), pour affichage dans l'UI |
| `CLARIFY_RESUME` | un prompt en chinois | « Reprends le clarify inachevé de tout à l'heure — **ce n'est pas un redémarrage**… ». Sans cette phrase, la continuité renverrait la demande initiale comme une nouvelle tâche et le clarifier pourrait reposer des questions déjà posées |

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

Produit un `Step` de **définition de l'objectif** : le [judge](glossary.md#判定者) lit le brief, écrit l'objectif + la liste de vérification, le tout parsé en [`Goal`](#goal), gelé puis écrit sur disque. Même forme que `clarify_step`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Canal de questions |
| `goal_path` | `str \| Path` | requis | Où atterrit le fichier d'objectif |
| `brief_key` | `str` | `"确认需求"` | Récupère le texte du brief dans `ctx[brief_key]` pour l'insérer dans le prompt. **S'il est introuvable, c'est `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nom du step |
| `spec` | `AgentSpec \| None` | `None` | Si absent, utilise `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions supplémentaires |
| `always_set` | `bool` | `False` | `True` = recalculer la liste, que le fichier d'objectif existe ou non |
| `on_fail` | `str` | `"stop"` | Comme ci-dessus |
| `retries` | `int` | `0` | Comme ci-dessus |
| `**spec_kw` | | | Transmis à [`judge()`](#judge-role) |

**Il n'y a pas de paramètre `can_run`** — pour que le judge qui pose l'objectif puisse exécuter des commandes, il faut passer `can_run=True` via `**spec_kw`. Sans cela il n'a pas `Bash`, et la règle « commence par bien voir dans quel environnement tu es » de `JUDGE_RULES` est inapplicable.

En plus du parsing et du gel, la `gate` fait une chose supplémentaire : quand l'objectif contient des entrées `[此环境无法验证:…]`, elle émet **immédiatement**, via `ctx["_on_event"]`, un `Event("task", payload={"unverifiable", "total", "path"})` pour prévenir — le sort de ces entrées est scellé à l'instant où l'objectif est posé, et attendre le verdict signifie avoir déjà dépensé le coût d'une passe de travail complète.

**Aucun `resume_prompt` n'est défini** — poser l'objectif doit de toute façon renvoyer le brief intégral.

| Constante | Valeur | Description |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` est un objet `Goal` ; `ctx[step.name]` est le markdown |
| `VERDICT_KEY` | `"_verdict"` | Le dernier [`Verdict`](#verdict), pour l'UI |
| `ROUND_KEY` | `"_goal_rounds"` | Nombre de passes de verdict effectuées |

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

Enveloppe un `Step` existant d'un [goal guard](glossary.md#目标看守) : à la fin de chaque passe, le judge statue de façon indépendante, et si l'objectif n'est pas atteint le travail est renvoyé pour être poursuivi.

Le résultat est `replace(step, retries=max(0, rounds - 1), gate=<nouvelle gate>, on_reject=<nouveau on_reject>)` — avec `dataclasses.replace` plutôt qu'une reconstruction champ par champ ; une reconstruction a déjà laissé tomber `resume_prompt` une fois, **sans lever la moindre erreur**, simplement en renvoyant le brief entier à chaque reprise.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `step` | `Step` | requis, positionnel | Le step sous garde |
| `channel` | `HumanChannel` | requis, positionnel | Le canal pour demander de l'aide à un humain quand le verdict est bloqué |
| `goal_path` | `str \| Path` | requis | Le fichier d'objectif, lu ici quand `ctx[GOAL_KEY]` est incomplet |
| `spec` | `AgentSpec \| None` | `None` | Si absent, utilise `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Nombre total de passes, pas de passes supplémentaires** : `rounds=3` → `retries=2` → au plus trois passes de travail. `rounds=1` = une passe, un verdict, échec si le verdict ne passe pas |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le judge |
| `can_run` | `bool` | `False` | Le judge peut-il exécuter `Bash` |
| `name` | `str \| None` | `None` | Nom du judge, par défaut `f"{step.name}·判定"` |
| `**spec_kw` | | | Transmis à `judge()` |

La `gate` est **async**, déroulé :

1. `ctx["_runtime"]` absent → **lève `StepAbort`** (« impossible d'obtenir le Runtime, impossible de statuer sur l'objectif »). **Ne pas faire semblant que ça passe.**
2. `ctx[ROUND_KEY] += 1`.
3. Récupère l'objectif : d'abord un `Goal` complet dans `ctx[GOAL_KEY]`, sinon `Goal.load(goal_path)`, sinon un `Goal()` vide.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`. **Le judge est un `Runtime.run` indépendant, `resume` vaut toujours `None` — c'est toujours une nouvelle session** ; `step_name` porte le numéro de passe, donc n'entre pas dans le lineage inter-processus.
5. `Verdict.parse(vr.text)` est écrit dans `ctx[VERDICT_KEY]`.
6. `v.achieved` → retourne `True`.
7. Pas `unreachable` (y compris les cas ambigus avec `v.ok=False`) → en cas d'ambiguïté, ajoute une raison par défaut, retourne `False`. **L'ambiguïté vaut toujours objectif non atteint** — on ne laisse pas un « ça a l'air bon » clore le travail.
8. `unreachable` → `await channel.ask(...)` pour demander à l'humain, trois options :
   - Personne ne répond (`a.state != "answered"`) → **lève `StepAbort`**. Continuer à tourner à vide est le choix le plus cher.
   - « Accepter ce résultat et continuer ainsi » → retourne `True`.
   - « Modifier l'objectif » → redemande le nouvel objectif, `g.amend(...).write(goal_path)`, met à jour `ctx[GOAL_KEY]`, retourne `False`.
   - Le reste (y compris une réponse libre saisie par l'humain) → traité comme « ton verdict est faux » : la formulation de l'humain est enregistrée dans `v.reason`, retourne `False`.

`on_reject` est **synchrone** : retourne `ctx[VERDICT_KEY].feedback()`, ou `""` s'il n'y a pas de `Verdict` (on retombe sur un redémarrage depuis zéro).

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

Assemble un workflow en trois steps utilisable tel quel : **clarifier le besoin → poser l'objectif → travailler** (avec goal guard). C'est ce qu'utilise la commande `flower`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `ask` | `str` | requis, positionnel | Une phrase de demande. **Au réveil, ce n'est pas une nouvelle tâche, c'est « une phrase de plus »** |
| `workspace` | `str \| Path` | `"."` | Espace de travail |
| `run_dir` | `str \| Path` | `"runs"` | Répertoire de run |
| `new` | `bool` | `False` | `True` = archive lineage + brief + objectif (les trois ensemble) et repart de zéro |
| `isolate` | `bool` | `False` | Ouvre un worktree en [isolation](glossary.md#隔离) pour le worker. Le workbench se déplace en conséquence vers `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Retourne uniquement le Workflow contenant le step de clarify |
| `goal` | `bool` | `True` | Installer ou non le [goal guard](glossary.md#目标看守). `False` = le step de travail terminé, c'est fini |
| `rounds` | `int` | `3` | Transmis à `with_goal(rounds=)`, nombre total de passes |
| `judge_can_run` | `bool` | `False` | Transmis à `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Transmis à `HumanChannel`, `None` = sans limite |
| `timeout_s` | `float \| None` | `1800.0` | Transmis à `HumanChannel`. `0` = tout automatique, toutes les questions tombent immédiatement dans le vide |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le clarifier |
| `worker_prompt` | `str` | voir la signature | Le system prompt du worker |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier de brief, dans `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier d'objectif, idem |
| `log_name` | `str` | `"问答记录.md"` | Nom du fichier de journal des questions-réponses, idem |

Assemblage fixe :

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Branches de comportement :

- `isolate=True` alors que le workspace n'est pas un dépôt git → **lève une `ValueError`**, plutôt que d'attendre l'erreur de l'outil `Agent` pour s'en apercevoir (à ce moment-là l'argent est déjà dépensé).
- **Détection du réveil** : si `Brief.load(brief_path)` existe et que `complete()` est vrai, c'est un réveil. Si ce n'est pas un réveil et que `ask` est vide → **lève `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Au réveil, cette phrase atterrit simultanément à **trois endroits**, et il suffit qu'il en manque un pour qu'elle devienne silencieusement inopérante : ajoutée au brief (`ch.amend(said, label="唤醒时追加")`, sans réécriture si elle y figure déjà) ; `goal_step(always_set=True)` pour recalculer la liste (sans quoi le judge lirait encore l'ancien objectif) ; envoyée directement au coordinator (dont le contexte contient l'**ancien** objectif : sans cela il travaillerait selon l'ancien critère puis serait jugé selon le nouveau).

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

**Sonde en lecture seule avant le départ, pas un octet écrit.** Sert à dire à l'humain, avant de vraiment lancer, s'il s'agit d'une reprise ou d'un départ de zéro.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Espace de travail, positionnel |
| `run_dir` | `str \| Path` | `"runs"` | Répertoire de run |
| `isolate` | `bool` | `False` | Détermine l'emplacement du workbench, doit valoir la même chose que ce qui est passé à `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier de brief |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier d'objectif |

Le dict retourné :

| Clé | Type | Description |
|---|---|---|
| `waking` | `bool` | Le brief existe et ses quatre sections sont complètes |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Nombre d'entrées de la liste d'objectif, `0` s'il n'y a pas d'objectif |
| `woke` | `int` | `Lineage.woke`, nombre de réveils déjà effectués |
| `steps` | `dict` | Une copie de `Lineage.steps`, nom de step → `session_id` |

L'emplacement du workbench n'est **défini qu'ici et dans `starter_flow`** : `isolate=True` → `<ws>.parent/.flower-<ws.name>` (hors du dépôt) ; sinon `<ws>/.flower`. Un programme pilote qui veut savoir où est le brief passe aussi par cette fonction — reconstruire le chemin soi-même ne lève aucune erreur en cas d'erreur, ça devient simplement inopérant en silence.

---

## Fabrique de rôles {#角色工厂}

Source : [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Les cinq rôles sont des fonctions fabriques. Chaque rôle = **un texte de règles injecté + un jeu d'outils + un jeu de hooks**.
`worker()` produit une `AgentDefinition` du SDK (destinée à un subagent), les quatre autres produisent une [`AgentSpec`](#agentspec)
(qui démarre sa propre session).

Les rôles eux-mêmes **n'accrochent aucun hook** — l'interception des outils est montée automatiquement par
`Runtime._attempt` selon `spec.delegate_only`, voir [la couche hook](#hook).

Constantes internes des jeux d'outils (non exportées, mais qui déterminent les valeurs par défaut) :

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

Fabrique le [coordinateur](glossary.md#主线程) qui tourne sur le [thread principal](glossary.md#协调者) : il découpe la tâche, distribue le travail, lit les rapports, décide,
**mais ne met pas la main à la pâte**. Les trois premiers paramètres sont positionnels.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du rôle, également le nom d'étape par défaut |
| `instructions` | `str` | requis | Instructions métier. Le résultat final est `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | requis | Quels rôles il a sous la main, reporté dans `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Si fourni, ajoute **à la fois** les outils `inbox` **et** `ask`, et renseigne `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]` ; `False` → sans `Read` |
| `glance` | `bool` | `True` | Ajoute `"Bash"` et renseigne `AgentSpec.glance`. **Ce qui peut réellement s'exécuter est filtré par `delegate_guard`**, pas ici |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Mode de permission. **Attention à cette valeur par défaut** — la passer à `clarify()`/`judge()` démonte la protection de ces deux rôles |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, ne sera pas forcé en `no_summary` par le `Runtime` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks supplémentaires, fusionnés avec `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variables d'environnement supplémentaires |

Trois champs sont figés dans l'`AgentSpec` produite : `delegate_only=True`, `agents=workers`,
et `workbench` conserve la valeur par défaut `True` d'`AgentSpec`.

Le code source dit explicitement de **ne pas utiliser `disallowed_tools` pour obtenir « coordonner sans agir »** — c'est un réglage au niveau de la session,
qui désactiverait aussi `Bash`/`Write` chez les subagents, voir l'avertissement dans [`AgentSpec`](#agentspec).
La bonne approche est celle d'ici : `delegate_only=True` + ne rien mettre dans `allowed_tools`,
puis laisser [`delegate_guard`](#delegate-guard) n'intercepter que le thread principal via `agent_id`.

Fournir `channel`, c'est **prendre les deux outils ensemble**, ce n'est pas optionnel : dès que le serveur MCP est monté, les deux sont là, et
`allowed_tools` n'est pas exclusif — listés ou non, ils restent appelables. En mode non supervisé, chaque `ask` bloquera jusqu'au bout du `timeout_s` —
dans ce cas, utiliser `HumanChannel(timeout_s=0)`.

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

Fabrique la définition du [subagent](glossary.md#subagent) qui fait réellement le travail. Les deux premiers paramètres sont positionnels.
La valeur de retour est une `AgentDefinition` du SDK, à passer directement dans `coordinator(workers={...})`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `description` | `str` | requis | **Ce sur quoi le coordinateur s'appuie pour choisir** — écrire clairement « quel travail lui confier » |
| `prompt` | `str` | requis | Son system prompt. Si `discipline=True`, concaténé en `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Un exécutant ne doit pas être rétrogradé |
| `effort` | `str \| int \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Reporté sur le **`maxTurns`** du SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Reporté sur le **`permissionMode`** du SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Quelles skills il a le droit d'utiliser |
| `discipline` | `bool` | `True` | Concaténer ou non la discipline de compte rendu `WORKER_RULES` |
| `isolate` | `bool` | `False` | Pose la marque d'[isolation](glossary.md#隔离), passe par `isolated()`, **ce n'est pas un champ d'`AgentDefinition`** |

`isolate=True` exige que le workspace soit un dépôt git, sinon l'outil `Agent` renvoie directement `"not in a git repository"`,
**sans dégradation silencieuse**. Et comme la marque est un attribut Python, faire un `dataclasses.replace()` sur l'`AgentDefinition`
la perd, et l'isolation échoue silencieusement.

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

Fabrique le [clarificateur](glossary.md#确认者) : il tire le besoin au clair avant qu'on agisse, ne fait rien, ne pose que des questions, et produit à la fin exactement quatre sections.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du rôle, paramètre positionnel |
| `channel` | `HumanChannel` | requis | Canal de questions, paramètre positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Si `True`, ajoute `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | **Nombre de tours illimité** |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produite : `allowed_tools = [channel.tool_name] + (les cinq outils si lecture autorisée)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (il n'a pas d'outil d'écriture, l'index n'a aucun sens pour lui),
`permission_mode` hérite du défaut `"default"` d'`AgentSpec`.
**Pas de `Write` / `Edit` / `Bash` / `Agent`, ni d'`inbox`** (contrairement au coordinateur).

!!! warning "Mettre un petit `max_turns` réduit à néant le « nombre de questions illimité »"
    Chaque question est un tour. `max_turns=16` équivaut à « une quinzaine de questions au maximum » ; la phrase « pas de plafond de tours » du canal devient caduque sur-le-champ.

    Pour vraiment libérer les questions, il faut ouvrir **les deux** : `HumanChannel.max_asks` (déjà `None` = illimité par défaut)
    et `max_turns` (déjà `None` par défaut).

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

Fabrique le [juge](glossary.md#判定者) : soit il fixe l'objectif avant le départ, soit il rend un verdict à la fin de chaque tour.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du rôle, paramètre positionnel |
| `channel` | `HumanChannel` | requis | Canal de questions, paramètre positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Si `True`, ajoute `Bash` à la liste blanche ; `whitelist_guard` laisse alors passer `Bash` tout en bloquant `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produite : `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (si `can_run`) `["Bash"]`,
`workbench=False`, le reste comme `clarify()`. **Pas de `Write` / `Edit` / `Agent`, ni d'`inbox`.**

**Arbitrage** : `can_run=True` durcit le verdict (il peut réellement exécuter les commandes de recette), au prix de laisser le juge modifier l'espace de travail —
`Bash` permet d'écrire des fichiers. Pour un verdict absolument neutre, ne l'activez pas.

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

Fabrique l'[oracle](glossary.md#旁路顾问) : pendant qu'un run tourne encore, on lui demande « où en est-on ? » ; il jette un œil aux événements récents et à l'établi
avant de répondre. **Ce qu'il dit n'entre pas dans le contexte de ce run.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nom du rôle, paramètre positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | **`12`** | Frein par défaut |
| `max_budget_usd` | `float \| None` | **`0.5`** | Frein par défaut. C'est « une question en passant », ça ne doit pas déraper |

L'`AgentSpec` produite : `allowed_tools = ["Read", "Glob", "Grep"]` (**pas de channel** — il ne pose pas de questions,
il y répond), `workbench=True` (**le seul des cinq rôles à activer l'établi sans être coordinateur** — précisément parce qu'il doit aller lire les productions et les notes).

### Les cinq textes de règles {#rules}

Les cinq constantes figurent dans `__all__` : on peut les `import` telles quelles pour les lire, les concaténer, les modifier.

| Constante | Injectée à qui | Mode d'injection | Points clés |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Tu es « quelqu'un qui sait se servir de Claude Code », pas un exécutant ; interdit d'écrire des fichiers / modifier du code / lancer des tests ; `Bash` sert seulement à « jeter un œil » et le résultat se périme ; **la [fiche de tâche](glossary.md#任务书) ne contient que ce qui est propre à cette tâche** ; la seule règle qu'il reste à transmettre est « où est l'établi + les productions longues vont dans `artifacts/` + ne renvoyer que des chemins » ; consulter `inbox` après chaque action d'étape ; `ask` bloque, à n'utiliser qu'aux vraies bifurcations |
| `WORKER_RULES` | `worker()` | concaténé **après** le `prompt` du subagent | Format de compte rendu **结论 / 依据 / 产出 / 未验证**, 30 lignes maximum ; interdit de coller le contenu de fichiers, des sorties de commandes, des logs, des diffs bruts ; interdit de raconter les essais-erreurs ; regarder `.flower/scripts/` avant d'agir. **Ne mentionne délibérément pas « les productions longues vont dans `artifacts/` »** — le chemin réel est généré par `Workbench`, le figer serait faux |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Ne rien faire, seulement clarifier le besoin ; **aucune limite de nombre de questions, on interroge jusqu'à ce que ce soit clair** ; l'humain peut être absent, en cas de timeout trancher soi-même et l'écrire dans 「未知与假设」 ; produire **exactement quatre sections** ; ne pas écrire de code, ne pas coller de contenu de fichier |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Deux missions, une seule à la fois. **Fixer l'objectif** : chaque item de la liste doit être vérifiable sur-le-champ, la longueur de la liste est dictée par le nombre de modes de défaillance, **les limites ne sont pas des critères de verdict**, les items non vérifiables se terminent par `[此环境无法验证:原因]`. **Rendre le verdict du tour** : produire **exactement trois sections**, juger **les productions et non les sources**, ne pas croire par défaut le « c'est fait » ; « pas atteint » et « invérifiable ici » sont deux conclusions distinctes, la seconde **ne doit jamais donner un verdict de réussite** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Une voie latérale ; le run tourne encore, tu ne l'interromps ni n'y participes ; **lecture seule** ; réponse jetable, ce que tu dis n'entre pas dans le contexte de ce run ; tu ne disposes que de la « fenêtre des événements récents » et de l'« établi » ; regarder avant de répondre, dire qu'on ne peut pas répondre si c'est le cas, faire court |

---

## Définition d'agent {#agent-定义}

Source : [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` est la déclaration complète d'un agent spécialisé ; `build_options` la compile en `ClaudeAgentOptions` du SDK.
C'est ce que produit la [fabrique de rôles](#角色工厂) — pour toute combinaison hors fabrique, construisez-la directement.

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
| `name` | `str` | requis | Nom du rôle. C'est aussi le `step_name` par défaut de `Runtime.run`, et la manière dont l'agent se désigne dans le texte de refus de `whitelist_guard` |
| `instructions` | `str` | requis | Instructions métier. **[Ajoutées](glossary.md#叠加) après le system prompt natif de Claude Code, pas en remplacement** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Liste d'exemption d'approbation, pas une liste blanche exclusive** — le modèle peut toujours appeler un outil qui n'y figure pas. L'exclusivité passe par [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Au niveau de la session**. Voir l'avertissement ci-dessous |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Mode de permission |
| `agents` | `dict[str, Any] \| None` | `None` | Table des définitions de subagents, les valeurs sont des `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Table des serveurs MCP. `HumanChannel.mcp_servers()` la remplit directement |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks supplémentaires, que le `Runtime` fusionne avec les siens via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, ne sera pas forcé en `no_summary` par le `Runtime` |
| `env` | `dict[str, str]` | `{}` | Variables d'environnement injectées dans le sous-processus. `compact.env()` vient s'y ajouter par `update` |
| `glance` | `bool` | `False` | Autorise le coordinateur à lancer lui-même des `Bash` « pour jeter un œil ». Ce qui passe est décidé par [`is_ephemeral`](#is-ephemeral), et le résultat est marqué périmé par `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Injecter ou non l'index de l'établi dans le system prompt de cet agent. **À désactiver pour les rôles sans outil d'écriture** (`clarify()` / `judge()` sont déjà à `False`) |
| `delegate_only` | `bool` | `False` | Coordonner sans agir. À `True`, le `Runtime` monte `delegate_guard` et **ne monte pas** `whitelist_guard` |

!!! warning "`disallowed_tools` est au niveau de la session et désactive aussi les subagents"
    Message d'erreur constaté : `"Bash is disabled for this session, in subagents as well as here"`.
    Autrement dit, si vous utilisez `disallowed_tools=["Bash"]` pour empêcher le coordinateur d'agir, les exécutants délégués ne peuvent plus lancer de commandes non plus —
    tout le run est perdu.

    Pour « coordonner sans agir », utilisez `delegate_only=True` + ne rien mettre dans `allowed_tools`, et laissez
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

Compile une `AgentSpec` en `ClaudeAgentOptions` du SDK. C'est ce qu'appelle `Runtime._attempt` en interne ;
c'est aussi le point d'entrée si vous pilotez le SDK vous-même (sans `Runtime`).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | requis, positionnel | La déclaration à compiler |
| `cwd` | `str \| Path \| None` | `None` | N'écrit `cwd` que si non `None` |
| `session_store` | `SessionStore \| None` | `None` | N'écrit `session_store` et `session_store_flush` que si non `None` |
| `resume` | `str \| None` | `None` | Quelle session reprendre |
| `fork` | `bool` | `False` | Reporté sur `fork_session`. **Imbriqué dans `if resume:`** |
| `resume_at` | `str \| None` | `None` | Reporté sur `resume_session_at`. **Également imbriqué dans `if resume:`** |
| `use_plugin` | `bool` | `True` | Si `True` et que `PLUGIN_DIR` existe → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]` ; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Répertoires autorisés en plus. **Obligatoire quand l'établi est hors de l'espace de travail** |
| `flush` | `str` | `"eager"` | Reporté sur `session_store_flush` |
| `prelude` | `str` | `""` | Bloc ajouté après `instructions` (c'est par là que passe l'index de l'établi) |

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
| `resume` / `fork_session` / `resume_session_at` | **N'ont d'effet que si `resume` est vrai** |

`PLUGIN_DIR` est le répertoire `plugin/` à la racine du dépôt (trois niveaux au-dessus de `flower/core/agent.py`). Après une installation pip, ce répertoire n'existe pas forcément ;
le code le vérifie avec `is_dir()`.

!!! warning "`fork=True` sans `resume` est silencieusement sans effet"
    `fork_session` et `resume_session_at` sont tous deux imbriqués dans `if resume:` — sans `resume`, ils n'ont aucun effet,
    **et aucune erreur n'est levée**. De même, `Runtime.run(resume_at=...)` n'agit que si `resume` est fourni,
    et **`Workflow` ne transmet jamais `resume_at`** : pour revenir en arrière au message près, il faut appeler `Runtime.run` directement.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Le tableau de bord de l'auto-[compact](glossary.md#压缩) ; le produit est un jeu de variables d'environnement à injecter dans le sous-processus.
L'algorithme de compact lui-même est dans le binaire du harness et n'est pas modifiable ; seul le « déclenche-t-on ou non » l'est.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = on ne règle rien, seuil = fenêtre − 33k ; `"no_summary"` → `DISABLE_AUTO_COMPACT=1` ; `"off"` → `DISABLE_COMPACT=1` (coupe aussi `/compact`). **Toute autre valeur lève `ValueError`**, sans ignorance silencieuse |
| `window` | `int \| None` | `None` | Non `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Côté CLI, la plage est 100k–1M ; une valeur inférieure à 100k est remontée à 100k |

| Méthode | Signature | Description |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produit les variables d'environnement. **C'est ici qu'un `mode` invalide lève `ValueError`, pas à la construction** — comme elle est appelée par `build_options`, l'erreur remonte dans `Runtime.run` |

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

L'objet de politique qui, quand le contexte approche de la saturation, préfère « écrire un [document de passation](glossary.md#交接书) et repartir sur une nouvelle session » plutôt que de compacter.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Désactivé, on retombe sur l'auto-compact |
| `window` | `int` | `default_window()` | Taille supposée de la fenêtre de contexte du modèle |
| `headroom` | `int` | `50_000` | Marge conservée. Raison : l'auto-compact se déclenche à fenêtre −33k, la passation doit donc arriver avant, et « écrire la passation » consomme elle-même un tour |
| `max_generations` | `int` | `8` | Nombre maximal de générations par étape. **C'est un frein anti-emballement, pas un dimensionnement de capacité** |

| Propriété | Type | Description |
|---|---|---|
| `at` | `@property -> int` | Seuil de passation `max(10_000, window - headroom)`. **Plancher à 10k** — en dessous, on n'arrive même plus à écrire la passation |
| `warn_at` | `@property -> int` | Position de l'alerte d'approche `max(1_000, at - 20_000)`, émise une seule fois par génération |

!!! warning "Un `window` trop petit provoque des passations infinies et brûle de l'argent"
    Si `at` tombe sous le **plancher de démarrage** du rôle (environ 34k mesuré pour le coordinateur), chaque nouvelle session franchit la ligne dès sa première prise de parole ; et
    **une passation ne consomme pas de quota de reprise** (`attempt -= 1`), d'où une boucle à vide infinie. Le seul frein est `max_generations=8` ;
    une fois atteint, `error` est remplacé par un diagnostic invitant à augmenter `window` ou à désactiver la passation.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Devine la fenêtre de contexte à partir de la **chaîne de nom de modèle** des variables d'environnement `ANTHROPIC_MODEL` ou `ANTHROPIC_DEFAULT_OPUS_MODEL` :

| Condition | Retour |
|---|---|
| Le nom contient le mot isolé `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| Le nom contient `haiku` | `200_000` |
| Tous les autres cas (**y compris quand aucune des deux variables n'est définie**) | `1_000_000` |

**La valeur par défaut est optimiste.** Surestimer n'est pas une erreur dure : l'API renvoie `prompt is too long`, le `Runtime` reconnaît ce signal
(via son `is_overflow` interne) et bascule immédiatement en passation — mais la passation de cette génération est une version dégradée.

---

## Documents {#文书}

Sources : [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatre dataclasses, toutes du type « analyser une réponse du modèle en un nombre fixe de sections, puis l'écrire sur disque ». Forme commune :
`parse()` analyse, `missing()` / `complete()` vérifient la complétude, `to_markdown()` pour les humains,
`prompt_block()` pour les modèles en aval, `write()` / `load()` pour l'écriture et la relecture.

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

Le [cahier de besoin](glossary.md#需求确认书), **exactement quatre sections**, dans l'ordre fixe
`goal` → `accept` → `bounds` → `unknowns` ; les noms de section en chinois sont respectivement 「目标」「验收标准」「边界」「未知与假设」.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `goal` | `str` | `""` | Objectif |
| `accept` | `str` | `""` | Critères de recette |
| `bounds` | `str` | `""` | Limites |
| `unknowns` | `str` | `""` | Inconnues et hypothèses |
| `path` | `Path \| None` | `None` | Emplacement sur disque. `compare=False`, exclu du test d'égalité |

| Méthode | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | Les **noms chinois** des sections manquantes, directement affichables |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Analyse les quatre sections depuis la réponse du modèle. **Retire d'abord les blocs de code délimités** ; ce qui n'est pas trouvé reste vide |
| `to_markdown` | `() -> str` | Document complet avec métadonnées d'en-tête, les sections vides deviennent `"(未填)"` |
| `prompt_block` | `() -> str` | Version compacte pour l'aval, **ne contient que les sections non vides**, sans métadonnées |
| `write` | `(path: str \| Path) -> Path` | Crée le répertoire parent, écrit, affecte à `self.path` le chemin résolu et le renvoie |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Renvoie `None` si le fichier n'existe pas ou en cas d'`OSError`. **Reconvertit le marqueur `"(未填)"` en chaîne vide** |

Règles d'analyse (là où se concentrent les pièges) :

- Lors du retrait des blocs délimités, **une ``` ou un `~~~` non refermé fait jeter tout ce qui suit** — en pratique, le clarificateur colle parfois tout un fichier de code dans sa réponse.
  Quand la sortie du modèle est tronquée, plus aucune section suivante n'est analysable, donc `complete()` vaut `False` et la gate renvoie le travail.
- La regex des titres tolère `## 目标` / `**目标**` / `目标:` / `3. 边界`, et tolère aussi le corps de texte collé juste après le titre.
- La table d'alias est compilée par longueur décroissante, sinon "未知" avalerait "未知与假设" en premier.
- En cas de sections homonymes répétées, **on prend la première non vide**.
- Si, en éditant le cahier à la main, vous recopiez le marqueur `"(未填)"` de `to_markdown()`, la section reste comptée comme manquante.

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

Le [document de passation](glossary.md#换代) écrit au moment du [changement de génération](glossary.md#交接书), cinq sections.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `doing` | `str` | `""` | Ce qui est en cours. **Obligatoire** |
| `decided` | `str` | `""` | Ce qui a été décidé |
| `deadends` | `str` | `""` | Les impasses |
| `next` | `str` | `""` | L'étape suivante. **Obligatoire** |
| `scene` | `str` | `""` | L'état des lieux |
| `step` | `str` | `""` | Sert uniquement à l'en-tête du document, **n'entre pas dans l'analyse** |
| `path` | `Path \| None` | `None` | Emplacement sur disque |

**Seules `doing` et `next` sont obligatoires** — exiger que « les impasses » soit non vide pousserait le modèle à inventer.

| Membre | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Ne vérifie que les deux sections obligatoires** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Le corps porte-t-il le marqueur de dégradation `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Réutilise le découpeur de `Brief` |
| `to_markdown` | `() -> str` | Les sections vides deviennent `"(空)"` |
| `prompt_block` | `() -> str` | **L'en-tête dit explicitement au successeur « tu prends la suite »**, pour l'empêcher de retourner demander le contexte |
| `write` | `(path) -> Path` | Comme `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Comme `Brief.load` |

Trois membres **non exportés mais sémantiquement décisifs** dans le même module : `is_overflow(*texts)` reconnaît `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, etc., et transforme une « erreur dure » en « passation immédiate » ; `HANDOFF_PROMPT` est le prompt qui demande
**à la session courante elle-même** d'écrire la passation (avec les deux placeholders `{used}` et `{window}` ; **ce n'est pas un nouveau rôle** —
elle seule dispose de ce contexte) ; `degraded(step, prompt, *, why="")` assemble mécaniquement une passation quand elle n'a pas pu être écrite,
en fourrant dans `scene` les **1200** premiers caractères de la tâche d'origine.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

L'objectif et la liste de vérification du [gardien d'objectif](glossary.md#目标看守).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `statement` | `str` | `""` | Énoncé de l'objectif |
| `checks` | `list[str]` | `[]` | Liste de vérification, un item par ligne |
| `path` | `Path \| None` | `None` | Emplacement sur disque |

| Membre | Signature | Description |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Les items de `checks` marqués `[此环境无法验证:…]`. **Condamnés à ne jamais passer dès l'instant où l'objectif est fixé** |
| `missing` | `() -> list[str]` | Exige `statement` non vide **et** `checks` non vide |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | Un item de `checks` par ligne, les marqueurs `-` / `*` / `1.` sont retirés automatiquement |
| `to_markdown` | `() -> str` | Écrit `"(空)"` quand la liste est vide |
| `prompt_block` | `() -> str` | Version compacte pour l'aval |
| `write` / `load` | Comme `Brief` | Écriture et relecture |
| `amend` | `(extra: str) -> Goal` | **Ajoute sans écraser** : concatène `"\n\n(已修改)" + extra` après `statement`, renvoie `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Le résultat d'un verdict de tour rendu par le [juge](glossary.md#判定者), **exactement trois sections** : conclusion / motif / non passés.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"` ; `""` si l'analyse échoue |
| `reason` | `str` | `""` | Motif |
| `failed` | `list[str]` | `[]` | Les items de la liste non passés |

| Membre | Signature | Description |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | A-t-on réussi à extraire une conclusion. **`ok=False` doit être traité comme « non atteint », jamais comme atteint** |
| `parse` | `@classmethod (text) -> Verdict` | Voir ci-dessous |
| `feedback` | `() -> str` | Le retour renvoyé à l'exécutant : uniquement « ce qui manque », pas la solution |

Ordre de reconnaissance de `parse` :

1. Chercher d'abord la section titrée 「结论」/「判定」.
2. En l'absence de section titrée, sur le texte entier après strip : `fullmatch(r"1|true")` → atteint ; `fullmatch(r"0|false")` → pas encore.
3. Sinon, chercher dans le texte de conclusion le premier mot d'état trouvé dans la table (**mots longs en premier**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 sont tous rangés dans `unreachable`** —
   cas réellement vécu : plateforme cible macOS, exécution dans un conteneur Linux, et le juge a validé après avoir lu la branche du code source.
4. Toujours rien → chercher un `\b1\b` isolé → atteint, `\b0\b` → pas encore.
5. Aucun cas ne correspond → `state=""`, `ok=False`.

`unreachable` et `not_yet` **sont deux conclusions différentes** : la première emprunte la voie « on s'arrête et on demande à l'humain », pas celle du « on refait un tour ».

## Couche hook {#hook}

Source : [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Cette couche est la **frontière d'exécution** de flower : quels outils le main thread n'a pas le droit de toucher, comment on trim un résultat trop long, quel rôle part dans un worktree isolé —
tout est imposé par les hook du SDK, **pas par le prompt**. La raison est directe — un prompt est une suggestion, le modèle peut ne pas l'écouter : on a mesuré que même quand le system prompt dit explicitement « n'utilise pas de worktree », l'injection d'`isolate_guard` prend effet quand même (le modèle passe `None`, ce qui atterrit est `'worktree'`).

Neuf exports : cinq fabriques de guard qui renvoient un `HookMatcher` (`whitelist_guard` peut renvoyer `None`), un assembleur, un fusionneur, deux fonctions de marquage d'isolation.
Il n'y a pas besoin de les accrocher à la main — [`Runtime`](#runtime) les assemble automatiquement d'après l'`AgentSpec`. L'accrochage manuel n'est nécessaire que lorsqu'on pilote le SDK soi-même (sans passer par `Runtime`).

**La détection du main thread passe par une seule fonction** : `_is_main_thread(data) = not data.get("agent_id")` —
les données de hook du tool-lifecycle d'un subagent portent un `agent_id`, le [main thread](glossary.md#主线程) n'en porte pas.
Tous les guard « n'intercepter que le main thread » reposent sur cette ligne.

Constantes de groupes d'outils (niveau module, non exportées, mais elles déterminent le matcher par défaut) :

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Aide-mémoire : quel guard sur quel événement SDK {#hook-速查表}

| Fonction | Événement hook SDK | matcher | Cible interceptée | Ce qui est renvoyé | Qui l'installe |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | ceux de `Bash\|Write\|Edit\|NotebookEdit` qui **ne sont pas dans `allowed_tools`** | **uniquement le main thread** appelant un outil interdit | `permissionDecision: "deny"` + raison | `Runtime._attempt`, **seulement si `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (`tools=` modifiable) | **uniquement le main thread** mettant la main à la pâte ; avec `allow_glance=True`, un `Bash` qui passe `is_ephemeral()` est laissé passer | `deny` + « va déléguer un subagent » | `workbench_hooks(delegate_only=True)`, **seulement si `Runtime` a un workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` n'a ni `cwd` ni `isolation`, et le `subagent_type` a été marqué par `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injecte `isolation="worktree"`) | `workbench_hooks`, **seulement s'il y a un rôle marqué dans `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` tombe dans `workbench.root` | `{}` (l'effet de bord est `workbench.refresh()`) | `workbench_hooks`, toujours installé |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | les **champs chaîne** de `tool_response` de ≥ `threshold` caractères ; la lecture du répertoire de spill lui-même est laissée passer | `updatedToolOutput` (spill + une ligne de pointeur + 400 premiers caractères) | `workbench_hooks`, **seulement si `spill_threshold` est vrai** |

**La déduction clé que cette table permet de lire** : avec `Runtime(workbench=False)`, `workbench_hooks` n'installe rien du tout ;
et pour un coordinateur en `delegate_only=True`, `whitelist_guard` est également sauté — **le main thread n'a pas le moindre mur**.
Voir l'avertissement de [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Rend `allowed_tools` réellement exclusif pour les quatre outils qui mettent la main à la pâte.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `allowed` | `list[str] \| None` | requis, positionnel | on passe généralement directement `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | l'auto-désignation dans le texte de refus. `Runtime` passe `spec.name` |

- **Accroché sur `PreToolUse`**, le matcher est `"|".join(banned)`, `banned` = ceux de `Bash` `Write` `Edit` `NotebookEdit` qui ne sont pas dans `allowed`.
- Un match donne `permissionDecision: "deny"`, texte à peu près : « XX n'a pas YY. **C'est intentionnel, ce n'est pas une config manquante.** Écris la conclusion dans le corps de ta réponse, le framework la récupérera là — n'essaie pas d'autres formulations pour contourner. »
- **N'intercepte que le main thread de la session**, les subagents passent — leurs outils sont décidés par `AgentDefinition.tools`.
- Renvoie **`None`** quand il n'y a aucun outil à intercepter (par exemple un rôle comme `worker()` avec la panoplie complète), ce dont l'appelant se sert pour décider s'il l'installe ou non.

**Pourquoi elle doit exister** : `allowed_tools` est une **liste de dispense d'approbation, pas une whitelist exclusive**. Deux preuves mesurées — un judge à qui on avait fixé un objectif a lancé `Bash` 11 fois ; dans une sonde à $0.1, un agent avec `allowed_tools=["Read"]` appelait quand même `Write`/`Bash`.
Donc le « pas d'outils d'écriture » de `clarify()` / `judge()` **repose sur ce hook**, pas sur la whitelist elle-même.

L'avantage, c'est qu'il dérive de `allowed_tools`, donc `judge(can_run=True)` conserve automatiquement `Bash` tout en interceptant `Write`/`Edit` — pas besoin d'interrupteur supplémentaire.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Le main thread met lui-même la main à la pâte → refus, avec l'indication du chemin.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. C'est une chaîne regex, pas une liste |
| `allow_glance` | `bool` | `False` | à `True`, si `tool_name == "Bash"` et [`is_ephemeral(command)`](#is-ephemeral) est vrai, on laisse passer |

- **Accroché sur `PreToolUse`**, le matcher est justement `tools`.
- Le main thread appelle un de ces quatre outils → deny, la raison **indique quoi faire ensuite** : utiliser l'outil `Agent` pour déléguer un subagent, en écrivant clairement l'objectif et les critères d'acceptation dans la tâche, et en lui demandant d'écrire ses longues productions dans `.flower/artifacts/`, sa réponse ne donnant que le chemin et la conclusion.
- Les subagents passent tous.

La différence avec `whitelist_guard` est la **formulation** : les deux interceptent le même lot d'outils, mais celle-ci dit « va déléguer », ce qui est plus juste.
Donc un rôle en `delegate_only=True` n'installe que celui-ci ; l'installer en double ferait recevoir au modèle deux consignes contradictoires.

Le critère de laisser-passer d'`allow_glance=True` et la question « le résultat sera-t-il trimmé » sont la **même fonction** ([`is_ephemeral`](#is-ephemeral)) — l'ensemble laissé passer doit être égal à l'ensemble qui expire, modifier l'un oblige à modifier l'autre.

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

Un résultat d'outil qui dépasse le seuil est **spillé sur-le-champ** ([spill](glossary.md#落盘)), le contexte ne garde qu'une ligne de pointeur — pas d'attente que le contexte soit plein pour revenir compacter.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | requis, positionnel | le répertoire de spill est `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | à partir de combien de caractères on spille |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (défaut) = les résultats des subagents sont aussi spillés |

- **Accroché sur `PostToolUse`**, renvoie
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <trimmé>}}`.
- Le nom du fichier de spill est les 16 premiers caractères du `sha256` du contenu + `.txt`, remplacé dans le contexte par une ligne de pointeur + les **400 premiers caractères**.
- `updatedToolOutput` **doit conserver la structure de sortie de l'outil d'origine**, donc on ne remplace que les **champs chaîne** trop longs du dict ; **on ne touche jamais aux list** (elles peuvent contenir des blocs image). Une structure incorrecte est rejetée (l'original reste tel quel, sans erreur).
- **Lire le fichier de spill lui-même doit être laissé passer** — sinon « le lire avec `Read` » serait une parole vide : le texte complet relu serait de nouveau spillé, boucle infinie. On l'a rencontré en pratique, le modèle a essayé cinq formulations pour contourner.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Dès qu'on a écrit quelque chose dans le [workbench](glossary.md#工作台), rafraîchit `INDEX.md`, pour que l'agent suivant sache dès le départ qu'il existe.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | requis, positionnel | portée de détection et objet à rafraîchir |

**Accroché sur `PostToolUse`**, matcher `"Write|Edit"`. Si après résolution le `tool_input["file_path"]` tombe dans `workbench.root`, on appelle `workbench.refresh()`. **Renvoie toujours `{}`** — il ne modifie rien, il n'a que des effets de bord.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Attribue à un subagent un git worktree indépendant selon son rôle, pour réaliser l'[isolation](glossary.md#隔离).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | requis, positionnel | table des rôles, sert à vérifier si le `subagent_type` a été marqué |
| `on_inject` | `Any` | `None` | callback optionnel, appelé sous la forme `on_inject(subagent_type, description)` |

**Accroché sur `PreToolUse`**, matcher `"Agent"`. Trois conditions doivent être réunies simultanément pour injecter : `tool_name == "Agent"`, `tool_input` **n'a ni `cwd` ni `isolation`**, et le rôle correspondant au `subagent_type` a été marqué par `isolated()`.
Si oui, renvoie `permissionDecision: "allow"` + `updatedInput` (met `isolation` à `"worktree"`).

`isolation` et `cwd` sont **mutuellement exclusifs** dans l'outil `Agent` — si le modèle a lui-même spécifié un `cwd`, on le respecte.
« Faut-il isoler » est un **attribut du rôle**, pas un interrupteur global, ni une décision à chaque délégation ; un rôle qui n'a pas besoin d'isolation ne se verra pas ajouter le moindre octet.

**Activer l'isolation impose de déplacer le [workbench](glossary.md#工作台) hors du dépôt.** Un agent isolé ne peut pas écrire dans le checkout partagé, donc le workbench doit pointer hors du dépôt avec `home=`. `starter_flow(isolate=True)` utilise `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` utilise `<run_dir>/workbench` — les deux sont hors du dépôt, **mais ce n'est pas le même répertoire**, ne les mélange pas.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marque une définition de subagent comme « a besoin d'un espace de travail indépendant », et relit ce marquage.

| Fonction | Paramètre | Défaut | Description |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | requis | la définition à marquer. **Renvoie le même objet** |
| | `flag: bool` | `True` | positionnel. `False` = retire le marquage |
| `wants_isolation` | `agent: AgentDefinition \| None` | requis | accepte aussi `None`, renvoie `False` |

Le marquage passe par un attribut côté Python `_flower_isolate` posé via `object.__setattr__`, **ce n'est pas un champ de dataclass** — le SDK sérialise avec `asdict()`, qui ne reconnaît que les champs déclarés, donc ce marquage ne fuit pas vers le CLI (mesuré).

**Le coût** : faire un `dataclasses.replace()` sur un `AgentDefinition` perd ce marquage, l'isolation échoue silencieusement.

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

Installe en une fois les quelques hook dont le workbench a besoin. C'est ce qu'appelle `Runtime._attempt`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | requis, positionnel | passé à `index_guard` et `spill_guard` |
| `delegate_only` | `bool` | `True` | n'installe `delegate_guard` que si `True` |
| `spill_threshold` | `int \| None` | `4000` | n'installe `spill_guard` que si vrai |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | ajoute `isolate_guard` seulement si **au moins un** est marqué par `isolated()` |
| `allow_glance` | `bool` | `False` | transmis à `delegate_guard(allow_glance=)` |

Produit :

- `PreToolUse` : `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]` ;
  s'il y a un rôle marqué → ajoute `isolate_guard(agents)`.
- `PostToolUse` : toujours `[index_guard(workbench)]` ; si `spill_threshold` est vrai → ajoute `spill_guard(workbench, threshold=spill_threshold)`.
- **Les clés d'événement à liste vide sont retirées**, on ne renvoie pas de list vide.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatène** plusieurs groupes de configuration de hook par nom d'événement.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variadique | autant de groupes qu'on veut. Les groupes `None` sont sautés |

Utilise `extend`, **sans dédupliquer** — passer deux fois le même guard l'installe deux fois. `Runtime` s'en sert pour réunir `spec.hooks`, `workbench_hooks(...)` et `whitelist_guard`.

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

Le répertoire de travail du spill, trois sous-répertoires + un index. L'index est **injecté dans le system prompt**, donc l'agent sait à chaque tour ce qu'il a sous la main.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `Path` | requis, positionnel | l'espace de travail. `__post_init__` le résout |
| `dirname` | `str` | `".flower"` | nom du répertoire du workbench, relatif à `workspace` |
| `max_index_entries` | `int` | `40` | **ne concerne que `prompt_block()`** : dans le bloc injecté au system prompt, combien d'entrées au maximum par catégorie ; le surplus est replié en une ligne « … et N autres ». `INDEX.md` lui-même n'est pas limité, il liste tout |
| `home` | `Path \| None` | `None` | s'il est donné, on l'utilise comme `root`, **en ignorant `dirname`**. Résolu aussi s'il n'est pas `None` |

| Membre | Signature | Description |
|---|---|---|
| `root` | `@property -> Path` | `home` s'il est donné, sinon `workspace / dirname` |
| `external` | `@property -> bool` | si `root` est **en dehors** de `workspace`. Doit être `True` en mode isolation |
| `scripts` | `@property -> Path` | `root / "scripts"`, les scripts qu'on relancera |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, les longues productions de plus de 2000 caractères |
| `notes` | `@property -> Path` | `root / "notes"`, les décisions clés, un fichier par décision |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | le chemin montré au modèle : relatif à l'intérieur de l'espace de travail, absolu à l'extérieur |
| `ensure` | `() -> Workbench` | mkdir les trois répertoires, renvoie `self` (chaînable : `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(chemin d'affichage, description, octets)`. `rglob("*")` récursif, saute les fichiers commençant par `.` |
| `refresh` | `() -> str` | réécrit `INDEX.md` et renvoie le contenu |
| `prompt_block` | `() -> str` | **le bloc injecté au system prompt**. Fait court exprès — il est présent à chaque tour |

Format d'auto-description d'un script : un `# desc: une phrase` dans les 8 premières lignes (reconnaît aussi `//` et `--`), avec repli sur le premier commentaire non vide ou la première ligne du docstring (tronqué à 100 caractères).

Les trois règles injectées par `prompt_block()` :

1. Les scripts à relancer vont dans `scripts/`, première ligne `# desc:`.
2. Les productions dépassant **2000 caractères** vont dans `artifacts/`, la conversation ne donne que le chemin et la conclusion.
3. Les décisions clés vont dans `notes/`, un fichier par décision.

Quand `external=True`, `prompt_block()` insère une phrase supplémentaire « accède-y par chemin absolu ».

**L'index n'est pas hérité par les subagents.** Il passe par le `system_prompt.append` au niveau de la session, or un subagent a son propre system prompt (mesuré $0.2461). Donc les deux points « écris les longues productions dans `artifacts/` » et « où est le workbench » doivent être relayés par le [coordinateur](glossary.md#协调者) dans le [task brief](glossary.md#任务书) — **c'est le seul canal**, ce n'est pas redondant.
Ce point est **volontairement absent** de `WORKER_RULES` : le vrai chemin est généré par `Workbench`, le coder en dur serait faux.

---

## Session store {#会话存储}

Source : [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Trois couches par héritage : `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **utilise toujours la couche la plus externe** ; les stratégies des trois couches sont pilotées par les paramètres du constructeur.

Chacune des trois couches gère une chose : le spill, le [trim](glossary.md#裁剪) par volume et par valeur, le [prune](glossary.md#剪除) par « est-ce une erreur ou non ». Le trim et le prune se produisent tous deux au moment du **`load()`** (c'est-à-dire quand le resume renvoie l'historique au modèle) ; l'enregistrement brut dans SQLite ne bouge pas d'un octet.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implémente le protocole `SessionStore` du SDK, trois tables `entries` / `meta` / `summaries`.
La clé de store est `project_key/session_id[/subpath]` — **le transcript d'un sous-agent est distingué par subpath**.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `path` | `str \| Path` | requis, positionnel | le fichier de base de données. La connexion utilise `check_same_thread=False` |

| Méthode | Signature | Description |
|---|---|---|
| `append` | `async (key, entries) -> None` | idempotent par uuid (d'abord on retire ceux déjà en base, puis les doublons du lot). Lors d'un replay complet du lot, **ne fait pas avancer le mtime, ne refold pas les summary** ; seul le transcript principal (`subpath is None`) participe aux summary |
| `projects` | `() -> list[str]` | les `project_key` réellement présents en base. **Le SDK les déduit du cwd, confirme-les avec ceci avant de requêter, ne devine pas** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **synchrone, ne lit pas le payload**, ne consulte qu'une ligne de meta. Pour « continuité sur le même chemin » — resume une session inexistante n'exploserait qu'une fois le sous-processus démarré |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | quelle taille de contexte le modèle a réellement vu au dernier tour, renvoie `0` si introuvable. Ne parcourt à l'envers que les `scan` dernières entrées ; compte les trois `input + cache_read + cache_creation` (ne regarder que `input_tokens` sous-estime gravement) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | trié par seq ; renvoie `None` s'il n'y a aucune ligne |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | seulement le transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | liste les summary de session |
| `delete` | `async (key) -> None` | supprimer le transcript principal **supprime en cascade ceux des sous-agents**, pour éviter les orphelins |
| `list_subkeys` | `async (key) -> list[str]` | liste les sous-transcripts sous cette session |
| `close` | `() -> None` | ferme la connexion |

Le `_next_mtime` interne garantit une **stricte monotonie** — `list_sessions` et le sidecar de summary partagent cette horloge, sinon la fast path de staleness du SDK se tromperait.

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
| `keep_recent` | `int` | `20` | les N derniers `tool_result` gardent leur texte original |
| `min_chars` | `int` | `2000` | un résultat court ne vaut pas la peine d'être trimmé |
| `spill_dirname` | `str` | `".flower/spill"` | **relatif à `workspace`, doit être dans l'espace de travail** — sinon le `Read` de l'agent ne peut pas l'atteindre |
| `enabled` | `bool` | `True` | à `False` avec `Runtime(trim=False)` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | génère la ligne de pointeur qui remplace le corps |

**Les deux répertoires de spill ne sont pas le même.** `spill_guard` atterrit dans `<workbench.root>/spill/` (qui peut être hors de l'espace de travail) ;
`TrimPolicy.spill_dirname` atterrit dans `<workspace>/.flower/spill/` (**doit être dans l'espace de travail**).
Les deux correspondent respectivement à « trim sur-le-champ » et « trim au resume » ; les répertoires distincts sont intentionnels, ne les fusionne pas.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Stratégie d'expiration des résultats des [ephemeral command](glossary.md#一次性命令).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | à `False`, aucun marquage d'expiration n'est fait |
| `keep_recent` | `int` | `6` | les N derniers sont dispensés. **Bien plus petit que les 20 de `TrimPolicy`** |
| `max_chars` | `int` | `2000` | au-delà on saute, on laisse `TrimPolicy` archiver |
| `text` | `str` | voir signature | texte de remplacement, deux placeholders `{cmd}` et `{age}` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | applique `text` pour générer le corps de remplacement |

**N'agit que sur les résultats de l'outil `Bash`**, et la commande doit correspondre à la whitelist des ephemeral commands. **`Read` n'en fait pas partie** — le contenu d'un fichier ne se dénature pas avec le temps au point d'induire en erreur. Le contenu expiré **n'est pas spillé**, il est jeté directement.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Détermine si une commande Bash est une [ephemeral command](glossary.md#一次性命令).
**Le critère de laisser-passer de `delegate_guard` et le critère d'expiration du trim partagent cette même fonction** — l'ensemble des commandes que le coordinateur peut lancer lui-même doit être égal à l'ensemble des résultats qui seront marqués expirés. Laisser passer sans trimmer, et un `git status` expiré occuperait le contexte à jamais tout en induisant en erreur ; trimmer sans laisser passer, et le coordinateur déléguerait un subagent pour un simple `ls`, 4,3k de coût de démarrage contre quelques dizaines de caractères.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `cmd` | `str` | requis, positionnel | ligne de commande complète |

Ordre de décision :

1. Vide / tout en blanc → `False`.
2. Substitution de commande (`$(`, backticks, `<(`, `>(`) ou une écriture « qui change l'état » détectée → `False`.
3. Après avoir retiré les redirections sûres (`2>&1`, `&> /dev/null` et similaires), contient encore `>` ou `<` → `False`.
4. Après avoir retiré `&&` / `||` / `;` / `|`, reste un `&` isolé (exécution en arrière-plan) → `False`.
5. Découpe par `&&` / `||` / `;` / `|`, **chaque segment doit correspondre à la whitelist**.

Grandes catégories de verbes de la whitelist : sous-commandes `git` en lecture seule (`status` `diff` `log` `show` `branch` `rev-parse` etc.), infos répertoire et système (`ls` `pwd` `df` `du` `date` `whoami` `env` etc.), processus et conteneurs (`ps` `top` `lsof` `docker ps` `kubectl get` etc.), consultation de fichiers (`cat` `head` `tail` `wc` `stat` `find` `tree`), recherche de chemin (`which` `whereis` `command -v` `type`), traitement de texte (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` etc.).

Même si le verbe est dans la whitelist, ces écritures sont interceptées : `xargs`, `exec`, `eval`, `source`, `tee`, `find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` et `print >` dans `awk`, `git branch -D/-d/-m`, `git * --force/--hard/--prune`.

La première version refusait en bloc toutes les commandes composées, ce qui **a rendu le glance totalement inopérant en pratique** (les trois tentatives du coordinateur ont toutes été interceptées), d'où le passage à une décision segment par segment.

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
| `path` | `str \| Path` | requis | le fichier de base de données |
| `workspace` | `str \| Path` | requis | la base du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | non donné = `TrimPolicy()` par défaut |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | non donné = `EphemeralPolicy()` par défaut |

Attributs publics : `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

L'ordre de `load()` : `super().load()` → vide `last_report` → si `ephemeral.enabled`, `expire()` → si `policy.enabled`, `trim()`. **Quand `enabled=False`, l'étape est entièrement sautée.**

| Méthode | Description |
|---|---|
| `expire(entries)` | remplace **le corps seulement, les blocs restent** pour les résultats `Bash` éphémères expirés. La commande est retrouvée dans le `tool_use` du dernier message assistant ; saute `isCompactSummary` / `isMeta` ; saute ceux qui dépassent `max_chars` (laissés à `trim`) ; dispense les `keep_recent` derniers. Écrit `last_report["expired"]` |
| `trim(entries)` | les `tool_result` de `>= min_chars` ont leur corps spillé dans `<workspace>/<spill_dirname>/<16 premiers caractères du sha256>.txt`, le contenu du bloc devient un pointeur ; dispense les `keep_recent` derniers. Écrit `cleared` / `kept` / `chars_saved` dans `last_report` |

**Ne trim que le texte pur** : face à un bloc `image` / `document`, il le laisse tel quel.

**Deux lignes rouges structurelles** : le **bloc `tool_result` lui-même doit rester**, on ne peut remplacer que le content (en enlever un donne « Missing Tool Result Block ») ; on ne touche pas aux entrées `isCompactSummary`.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Rend `store.last_report` en une ligne de texte, pour les logs de l'UI.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | requis, positionnel | accepte aussi la sous-classe `PruningSessionStore` |

Trois sorties : aucune action → `"未裁剪"` ; expiration seule → `"N 个时效性结果标记为过期"` ;
sinon `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, où X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | retire les messages d'erreur API synthétiques (résidus de coupure) |
| `neutralize_interrupts` | `bool` | `True` | remplace les `tool_result` résiduels d'une interruption par une explication neutre |
| `interrupt_text` | `str` | voir signature | le texte de l'explication neutre |
| `keep_denials` | `int` | `1` | conserve les N derniers appels d'outil refusés |

La raison de `keep_denials` : un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information, mais son encombrement n'est pas négligeable (mesuré une fois 273 caractères = 93 caractères de formule de refus + 180 caractères de **texte de la commande morte**). Plus important encore, **il induit en erreur** — on a mesuré qu'après avoir lu quelques « n'utilise pas Bash directement », le coordinateur n'essayait même plus le `git status` autorisé, ayant appris l'impuissance apprise.
**On en garde 1 par défaut plutôt que 0** : le refus le plus récent empêche le modèle de retenter en boucle la même commande interceptée dans le même tour.

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
| `path` | `str \| Path` | requis | le fichier de base de données |
| `workspace` | `str \| Path` | requis | la base du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | stratégie de trim |
| `prune` | `PrunePolicy \| None` | `None` | stratégie de prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | stratégie d'expiration |

Les attributs publics ajoutent trois éléments à ceux de la classe parente : `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (d'abord `expire` + `trim`) → `self.prune(entries)`. `prune` fait trois choses :

1. **Retire les appels refusés trop anciens** : décidé par le marquage structurel du harness `toolDenialKind == "permission-rule"` (plus fiable que de matcher le texte de la formule de refus), conserve les `keep_denials` derniers, et retire pour les autres le bloc `tool_use` **et** le bloc `tool_result` ensemble. Quand un même message assistant contient plusieurs `tool_use`, **ne retire que celui visé**, sinon on obtient « Missing Tool Result Block » ; les blocs texte et thinking sont conservés.
2. **Retire les messages d'erreur API synthétiques.** Conservés tels quels dans SQLite, simplement pas renvoyés.
3. **Remplace les `tool_result` résiduels d'une interruption par une explication neutre** — remplace le corps seulement, ne retire pas l'entrée.

**La seule ligne rouge structurelle** : le transcript est une chaîne simple par `parentUuid`, retirer une entrée oblige à rattacher ses enfants à l'ancêtre survivant le plus proche.
Le `relink` interne exige que `entries` **soit la liste complète (y compris celles à retirer)**, le filtrage étant fait par lui-même — si l'appelant les retire d'abord avant de les passer, la chaîne se rompt là et tout l'historique antérieur est perdu (**déjà rencontré : invisible quand l'entrée retirée est en fin, explose quand elle est au milieu**).

**L'ordre des paramètres diffère de la classe parente** : le parent est `(path, workspace, policy, ephemeral)`, la sous-classe est `(path, workspace, policy, prune, ephemeral)` — **le quatrième paramètre positionnel passe d'`ephemeral` à `prune`**, un passage positionnel décale silencieusement. Passe toujours par mot-clé.

---

## Résilience {#韧性}

Source : [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

En cas de coupure réseau, attendre en suspens plutôt que quitter en échec. Quatre exports : une dataclass de stratégie + trois fonctions de sonde utilisables séparément.

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
| `enabled` | `bool` | `True` | à `False`, aucune panne n'est retentée |
| `max_attempts` | `int` | `6` | **inclut la première** |
| `base_delay` | `float` | `4.0` | base du backoff, en secondes |
| `max_delay` | `float` | `120.0` | plafond du backoff, en secondes |
| `probe_timeout` | `float` | `5.0` | timeout d'une sonde |
| `probe_interval` | `float` | `15.0` | combien de temps attendre entre deux sondes |
| `max_offline_wait` | `float` | `3600.0` | durée maximale d'attente en suspens, 1 heure par défaut |
| `retry_unknown` | `bool` | `True` | faut-il retenter une erreur inclassable |
| `resume_prompt` | `str` | voir signature | ce qu'on dit à la reprise. **Ne contient volontairement aucun détail d'erreur** — le modèle a besoin de savoir « j'ai été interrompu, je continue », pas de savoir si c'était `ENOTFOUND` ou 503 |

| Méthode | Signature | Description |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` puis multiplié par `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` avec `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | attend en suspens que le réseau revienne. Renvoie `True` s'il revient, `False` au-delà de `max_offline_wait`. `notify` est un callback `(str) -> None`, émis une fois **à la première inaccessibilité** et une fois **à la reprise** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classe le texte d'erreur en trois catégories `"transient"` / `"fatal"` / `"unknown"`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `text` | `str \| None` | requis, positionnel | le texte du message d'erreur. Vide → renvoie `"unknown"` |

**On juge fatal avant transient** — le texte d'un 401 et compagnie contient souvent le mot `connection`, inverser l'ordre ferait attendre indéfiniment.

| Catégorie | Ce qui matche |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

L'hôte et le port à sonder, suivant `ANTHROPIC_BASE_URL`, par défaut `https://api.anthropic.com` ;
port par défaut `80` (http) ou `443`.

**Sonder une passerelle auto-hébergée impose de la sonder elle** — que `api.anthropic.com` passe ne dit rien sur la passerelle.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `host` | `str` | requis, positionnel | nom d'hôte |
| `port` | `int` | requis, positionnel | port |
| `timeout` | `float` | `5.0` | secondes |

**Fait seulement le DNS (`getaddrinfo`) + le handshake TCP**, n'émet pas de HTTP, ne porte pas de credentials, **ne coûte rien**. Toute exception compte comme inaccessible.

---

## Événements et interaction {#事件与交互}

Sources : [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Un [événement](glossary.md#事件) est la structure stable en laquelle le flux de messages du SDK est aplati.
**La [couche d'interaction](glossary.md#交互层) ne connaît que `Event`, elle n'importe aucun type du SDK** — c'est la frontière qui permet de changer d'UI sans toucher au cœur. Voir [Remplacer la couche d'interaction](../guide/interaction.md).

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
| `kind` | `EventKind` | requis | voir la table ci-dessous |
| `text` | `str` | `""` | corps du texte |
| `tool` | `str` | `""` | nom de l'outil, présent uniquement sur `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | informations structurées additionnelles |
| `raw` | `Any` | `None` | objet SDK d'origine, pour creuser plus loin |

`__str__` : pour `tool_call` c'est `f"[{tool}] {text}"`, sinon `text`, et si `text` est vide `f"<{kind}>"`.
Donc `print(ev)` est directement lisible.

`EventKind` compte **15** valeurs au total :

| kind | Émetteur | Description |
|---|---|---|
| `text` | `normalize` | corps de texte de l'assistant |
| `thinking` | `normalize` | bloc de réflexion |
| `tool_call` | `normalize` | Appel d'outil. `text` est un résumé de `file_path` / `command` / `pattern`, coupé à 200 caractères |
| `tool_result` | `normalize` | Résultat d'outil. `text` coupé à 500 caractères, le payload porte `tool_use_id` / `is_error` |
| `task` | `normalize` | les trois sortes de messages Task, `text` est le nom de classe du message |
| `system` | `normalize` | les autres messages système, `text` est le subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, le payload porte `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | message d'erreur API synthétique, le payload porte `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Le corps est une entrée, pas une production du modèle**, il n'entre donc pas dans `StepResult.text` |
| `unknown` | `normalize` | non reconnu |
| `retry` | `Runtime` | notification de retry |
| `step` | `Workflow.run` | payload : `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | dans le payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | question, **porte aussi « ce que la personne dit spontanément »** |

**Les quatre derniers ne sont pas produits par `normalize()`.**

Le `payload` de tous les événements assistant / user porte :

| Clé | Type | Description |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | présent uniquement quand `subagent` est vrai |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **C'est la seule source du critère de [handoff](glossary.md#换代)**, et le chiffre qu'il faut le plus voir sur un run de longue portée |

**Le kind `ask` porte à la fois « une question » et « ce que la personne dit spontanément ».** Dans le second cas,
`payload["kind"] == "mail"` et **il n'y a ni `options` ni `remaining`**. L'UI doit d'abord tester
`payload.get("kind")` avant de décider du rendu, sinon elle laissera une simple phrase en suspens comme si
c'était une question à répondre.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Aplatit un message du SDK en 0 à N `Event`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `message` | `Any` | requis, positionnel | n'importe quel objet message du SDK |

Branches clés :

- **message d'erreur API synthétique** (`isApiErrorMessage=True` ou `model == "<synthetic>"`) → un unique
  `Event("error", payload={"synthetic": True})`. **C'est intentionnel** — sinon le texte de la coupure de
  connexion serait pris pour du corps de texte, entrerait dans `StepResult.text`, puis serait transmis à l'étape suivante.
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

Une question posée à la personne.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `id` | `str` | requis | sert à localiser la question au moment de répondre |
| `question` | `str` | requis | corps de la question |
| `options` | `list[str]` | `[]` | choix proposés. La personne peut aussi ne rien choisir et taper sa propre réponse |
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

Un **serveur MCP in-process** (deux outils) + un jeu de méthodes destinées à l'UI. Côté modèle, on ne voit que
`mcp__human__ask` et `mcp__human__inbox`. Tous les paramètres du constructeur sont keyword-only.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | La sortie du mode **push**. Si vous le fournissez, `Workflow.run` ne le recâblera pas |
| `max_asks` | `int \| None` | `None` | **Nombre de questions illimité**. Un nombre en fait un quota dur, `0` = questions interdites (tout automatique / CI). En cas de dépassement, l'outil **refuse directement, sans bloquer** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutes. `None` = attend indéfiniment ; **`<= 0` = n'attend pas, toutes les questions restent immédiatement sans réponse** |
| `log_path` | `str \| Path \| None` | `None` | Les questions-réponses sont **ajoutées en append** sur disque, sans occuper de contexte |
| `amend_path` | `str \| Path \| None` | `None` | Ce que la personne dit en cours de run est ajouté à ce fichier (en général le brief lui-même). **Sans spill sur disque, ça ne survit pas à la frontière d'étape** — l'étape suivante est une nouvelle session, qui ne lit que la version figée |
| `over_budget_text` | `str` | constante du module | ce qu'on renvoie au modèle en cas de dépassement de quota |
| `timeout_text` | `str` | constante du module | ce qu'on renvoie au modèle en cas de timeout |
| `declined_text` | `str` | constante du module | ce qu'on renvoie au modèle quand la question est passée |

Attributs publics : les huit homonymes des paramètres du constructeur, plus `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**les exceptions levées par les callbacks de l'UI sont collectées ici, sans interrompre le run**).

| Membre | Signature | Description |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | à passer directement à `AgentSpec.mcp_servers`. **Le nom de clé doit correspondre au nom du serveur**, c'est donc lui qui fournit les deux ensemble |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | bloque en attendant la personne. **Ne lève jamais d'exception, sauf `CancelledError`** — l'absence de réponse est aussi une réponse, on la distingue via `ask.state` |
| `send` | `(text: str) -> Mail \| None` | la personne dit spontanément quelque chose. **Appelable depuis n'importe quel thread.** N'interrompt pas l'agent ; appelle automatiquement `amend()` en interne |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | ajoute dans `amend_path`. Renvoie si l'écriture a réellement eu lieu (pas de chemin configuré, texte vide, `OSError` → `False`) |
| `pending_mail` | `() -> list[Mail]` | les mails non encore récupérés |
| `remaining` | `@property -> int` | combien de questions restent. **Renvoie `-1` quand `max_asks=None`**, ni 0 ni l'infini |
| `pending` | `() -> list[Ask]` | les questions actuellement en attente de réponse |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | pour le mode **pull**. Renvoie `None` en cas de timeout, lève si annulé |
| `answer` | `(ask_id: str, text: str) -> bool` | répond. `False` = cette question n'est plus en attente (timeout / déjà répondue) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | passe la question, laisse le modèle juger seul |
| `transcript` | `() -> str` | le markdown de l'historique des questions-réponses |

**Choisissez l'un des deux modes de récupération** : **push** — construire `HumanChannel(on_event=...)` ;
**pull** — `await channel.next_ask()`.
`Workflow.run` ne câble automatiquement que si `channel.on_event is None`, donc ce que vous passez vous-même ne sera pas écrasé.

**Multi-thread** : `answer` / `decline` / `send` passent en interne par `loop.call_soon_threadsafe`,
appeler depuis un backend Web ou un thread de saisie de TUI est le cas normal.

Les trois sémantiques « 0 / None » sont toutes différentes, ne les confondez pas : `max_asks=None` = illimité,
`max_asks=0` = questions interdites ; `timeout_s=None` = attend indéfiniment, `timeout_s<=0` = timeout immédiat ;
`remaining` vaut `-1` quand `max_asks=None`.

`Mail`, non exporté mais présent dans les valeurs de retour, est une dataclass aux champs `id` / `text` / `sent_at` / `taken`.

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

Enregistre entre processus « quelle étape a utilisé quelle session » ; c'est ce sur quoi la
[continuité](glossary.md#接续) s'appuie pour retrouver où le run précédent s'est arrêté.
Le fichier est `<run_dir>/lineage.json`.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `path` | `Path` | requis | chemin du fichier de lignage |
| `workspace` | `Path` | requis | espace de travail. `__post_init__` le résout |
| `steps` | `dict[str, str]` | `{}` | nom d'étape → `session_id` |
| `woke` | `int` | `0` | nombre de réveils |

| Membre | Signature | Description |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lit `<run_dir>/lineage.json`. **Fichier absent, illisible, ou champ `workspace` qui ne correspond pas : renvoie systématiquement un lignage vide, sans erreur** |
| `remember` | `(step: str, session_id: str) -> None` | mémorise le mapping et fait **immédiatement un spill sur disque**. Retourne directement si le step ou le sid est vide |
| `bump` | `() -> int` | incrémente le compteur de réveils de 1, spill sur disque, renvoie la nouvelle valeur (`1` au premier run) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **déplace** le fichier de lignage + `extra` vers `<into>/<YYYYmmdd-HHMMSS>/`, et remet `steps` / `woke` à zéro. **Déplacer n'est pas supprimer** |

Le spill sur disque passe par un remplacement atomique `tmp.replace(path)` ; les `OSError` sont avalées en silence —
un échec d'écriture ne doit pas emporter ce run.

**`workspace` est un garde-fou** : le `project_key` du SDK est dérivé du chemin de l'espace de travail ; si le
répertoire est copié ailleurs, les anciens `session_id` sont introuvables, donc un chemin qui ne correspond pas
équivaut à pas de lignage.

Quand `Workflow.run` charge le lignage, il valide chaque entrée une par une avec `runtime.has_session(sid)` pour
vérifier qu'elle est encore en base, et ne l'utilise que si elle est vivante — le fichier de lignage peut survivre
à `sessions.db`.

---

## Exemples minimaux exécutables {#示例}

Les cinq blocs se lancent tels quels. Prérequis : `claude-agent-sdk` installé, `ANTHROPIC_API_KEY` ou
`ANTHROPIC_AUTH_TOKEN` disponible (sinon `Runtime(...)` lève `RuntimeError` dès la construction).

### Un agent, une étape {#示例-单-agent}

Le squelette minimal : déclarer un `AgentSpec`, créer un `Runtime`, `await rt.run(...)`, lire le `StepResult`.

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

Les paramètres de `Runtime` sont **tous keyword-only** ; `spec` et `prompt` de `rt.run()` sont positionnels, le reste keyword-only.
`AgentSpec` a par défaut `allowed_tools=["Read", "Glob", "Grep"]` et `delegate_only=False`,
donc `Runtime` lui monte automatiquement [`whitelist_guard`](#whitelist-guard), qui bloque `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordinateur + exécutant {#示例-协调}

Un [coordinateur](glossary.md#协调者) qui ne touche à rien, avec un [exécutant](glossary.md#执行者) qui fait le travail.
C'est la première couche d'économie de contexte de flower.

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

    # workbench=True est obligatoire : delegate_guard est monté dans workbench_hooks,
    # sans workbench, les Bash/Write du coordinateur n'ont aucun hook pour les arrêter.
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

Les deux premiers paramètres de `worker()` sont positionnels : `description` (ce dont le coordinateur se sert pour
choisir) et `prompt` (son system prompt, auquel `WORKER_RULES` est concaténé automatiquement). Les trois premiers de
`coordinator()` sont positionnels : `name`, `instructions`, `workers`.

### Écrire son propre Workflow {#示例-workflow}

Deux étapes, la seconde injectant le résultat de la première dans son propre prompt — pas cher, isolé, sans session partagée.

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
        # Nouvelle session + résultat de l'étape précédente injecté dans le prompt (pas cher, anti-pollution)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Pour continuer dans la même session, écrire resume_from="造句" ; pour bifurquer, ajouter fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (quand reduce n'est pas fourni)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # avec on_fail="stop", à quelle étape l'échec a eu lieu


asyncio.run(main())
```

Les trois premiers champs de `Step` (`name` / `spec` / `prompt`) sont positionnels, de même que `steps` de `Workflow`.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positionnel, les deux callbacks keyword-only.
**Attention, `continuous=True` est la valeur par défaut** : au deuxième run avec le même `run_dir` et le même
`workspace`, les étapes dont `resume_from=None` reprendront elles aussi la session précédente.

### Ajouter un garde-objectif {#示例-目标}

D'abord laisser le [juge](glossary.md#判定者) fixer l'objectif et la liste de vérification, puis faire accepter le
verdict par l'étape qui travaille — si ça ne passe pas, on recommence avec le retour, trois tours au maximum.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = tout automatique : toutes les questions restent immédiatement sans réponse, on ne feint pas d'attendre
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
        # Sans clarify_step, remplissez-le vous-même, sinon il ne verra que "(没有确认书)".
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

`with_goal` ne remplace que `gate` / `on_reject` / `retries`, les autres champs sont repris tels quels via
`dataclasses.replace`.
Le juge tourne dans une **session indépendante** : le `gate` appelle en interne `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
avec `resume` toujours à `None`.

### Remplacer la couche d'interaction {#示例-交互层}

Pour passer du terminal au Web / TUI / HTTP, il n'y a que deux choses à changer : la fonction qui rend les `Event`,
et la coroutine qui récupère les questions.

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
    # Les kind == "ask" qui ne sont pas des mails sont traités par l'answerer ci-dessous (mode pull)


async def answerer(ch: HumanChannel) -> None:
    """Récupération des questions en mode pull. Pour un backend Web / un service HTTP, cette coroutine est le seul point à changer."""
    while True:
        ask = await ch.next_ask()          # sans timeout, attend indéfiniment
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime réutilise le workbench déjà créé par le workflow — n'en fabriquez pas un autre
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push et pull : **choisissez-en un**. Push, c'est construire `HumanChannel(on_event=...)` ; pull, c'est
`await channel.next_ask()`.
`Workflow.run` ne câble automatiquement que si `channel.on_event is None`, donc si vous passez vous-même `on_event`
il ne sera pas écrasé.
`answer()` / `decline()` / `send()` / `interrupt()` **sont tous appelables depuis un autre thread**.

---

## Pièges et erreurs fréquentes {#陷阱}

Classés dans l'ordre où on les rencontre, pas par module. Chaque point vient d'une observation réelle.

### Assemblage {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = pas un seul mur sur le thread principal.**
   `delegate_guard` n'est monté que s'il y a un workbench, et `whitelist_guard` est court-circuité par
   `delegate_only=True`. Si vous utilisez un coordinateur, activez le workbench. Voir [Runtime](#runtime).
2. **Il y a deux emplacements de workbench, ne les mélangez pas.** `Runtime(workbench=True)` tombe dans
   `<run_dir>/workbench` ; `Workbench(ws)` vaut par défaut `<ws>/.flower`. Quand on fabrique soi-même `brief_path`
   on l'écrit d'après le second : **le brief part dans le répertoire A, l'index injecté balaie le répertoire B, et
   rien ne signale l'erreur**.
   La bonne façon : le workflow fait lui-même `Workbench(...).ensure()`, l'attache à `Workflow.workbench`,
   puis confie **le même objet** à `Runtime(workbench=wb)`.
3. **`allowed_tools` n'est pas une liste blanche exclusive, c'est une liste de dispenses d'approbation.**
   Le modèle peut toujours appeler des outils qui n'y figurent pas.
   Le fait que `clarify()` / `judge()` « n'ont pas d'outil d'écriture » repose sur le hook
   [`whitelist_guard`](#whitelist-guard).
   Et `coordinator()` a par défaut `permission_mode="acceptEdits"` — si quelqu'un passe cette valeur à
   `clarify()` / `judge()`, la protection disparaît.
4. **`disallowed_tools` est au niveau de la session** : il interdit aussi les outils du même nom chez les subagents.
5. **L'index du workbench n'entre pas dans les subagents.** « Écrire les productions longues dans `artifacts/` »
   doit être relayé par le coordinateur dans le brief de tâche, c'est le seul canal.
6. **`Runtime(...)` lève `RuntimeError` dès la phase de construction s'il n'y a pas de credentials**, pas au moment de `run()`.
7. **`Runtime.run_id` doit être unique par instance.** `manifest.json` déduplique sur le champ `run` ; si deux ids
   collident, celui qui écrit en dernier prendra les lignes de l'autre pour « ce qu'il a écrit la fois précédente » et les supprimera.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` est la valeur par défaut**, `resume_from=None` ne veut pas dire « session
   entièrement neuve ». Pour repartir de zéro à chaque fois, mettez explicitement `continuous=False`.
   **Changer un nom d'étape équivaut à couper le lignage.**
9. **`with_goal(rounds=N)` est le nombre total de tours, pas le nombre de tours supplémentaires** :
   `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` n'écrit pas `ctx[step.name]`** — un `lambda ctx: ctx["某步"]` en aval lèvera `KeyError`.
    Pour continuer avec un résultat incomplet, utilisez `on_fail="continue"`.
11. **Un `resume_from` qui pointe vers une étape non exécutée / en échec lève `ValueError`**, il n'est pas ignoré en silence.
12. **`Step.reduce` doit être une fonction synchrone ; `gate` / `when` / `on_reject` peuvent être async.**
13. **`fork=True` est silencieusement sans effet si `resume` n'est pas fourni.** `Workflow` ne transmet jamais
    `resume_at` ; pour revenir en arrière au niveau du message, il faut appeler directement `Runtime.run`.
14. **Quand on pilote `Runtime` soi-même, `on_session` doit être retiré avant le gate**, sinon la session du juge
    sera inscrite dans le lignage de l'étape qui travaille. `Workflow` le garantit avec un `try/finally`.
15. **`step_name` détermine les clés dans le manifest et le lignage.** `Workflow` ajoute des suffixes
    `#retryN` / `#roundN`, le juge ajoute `#轮次` — **les noms suffixés n'entrent pas dans le lignage
    inter-processus**, c'est précisément une des façons dont « le juge est toujours une nouvelle session » est implémenté.

### Rôles {#陷阱-角色}

16. **`clarify(max_turns=<petit nombre>)` rend vide la promesse « nombre de questions illimité »** — chaque question consomme un tour.
17. **`goal_step()` n'a pas de paramètre formel `can_run`**, il faut passer `can_run=True` via `**spec_kw`.
    Sans ça, le juge qui fixe l'objectif n'obtient pas `Bash`, et la consigne de `JUDGE_RULES`
    « commence par bien voir dans quel environnement tu es » ne peut pas être exécutée.
18. **`judge(can_run=True)` permet au juge de modifier l'espace de travail** — `whitelist_guard` est dérivé de
    `allowed_tools` : si vous donnez `Bash`, `Bash` passe (`Write`/`Edit` restent bloqués, mais `Bash` lui-même sait
    écrire des fichiers). Pour une neutralité absolue, ne l'activez pas.
19. **`worker(isolate=True)` exige que le workspace soit un dépôt git**, sinon l'outil `Agent` renvoie directement
    `"not in a git repository"`, sans dégradation silencieuse. De plus, le marqueur d'isolation est un attribut
    Python : **faire `dataclasses.replace()` sur un `AgentDefinition` le perd**.
20. **Quand on construit directement un `AgentDefinition`, les paramètres sont en camelCase** : `maxTurns`, `permissionMode`.
    `worker()` fait déjà la conversion pour vous.

### Handoff et contexte {#陷阱-换代}

21. **Quand le handoff est actif, l'auto-compact est forcé à off, sans filet.** L'étape qui écrit le handoff doit
    donc avoir un chemin de dégradation. Pour conserver l'auto-compact, fournissez explicitement `AgentSpec.compact`.
22. **Un `HandoffPolicy.window` trop petit provoque des handoffs sans fin et brûle de l'argent.** Le seul frein est
    `max_generations=8`.
    À l'autre bout, **`default_window()` renvoie aussi `1_000_000` quand aucune des deux variables d'environnement
    n'est définie** — une valeur trop grande est rattrapée par `is_overflow()` (qui la transforme en un handoff
    dégradé), ce n'est pas une erreur dure, mais le handoff de cette génération est dégradé.
23. **Sans workbench, le handoff ne fait pas de spill sur disque.** Le document est tout de même transmis au
    successeur par le prompt, mais personne ne pourra le retrouver après coup.

### Stockage {#陷阱-存储}

24. **`Runtime(trim=False)` (le défaut) ne veut pas dire « rien n'est nettoyé ».** Le store est toujours un
    `PruningSessionStore` ; `trim=False` ne désactive que le trim des gros résultats. **Le retrait des résidus de
    déconnexion, le retrait des appels refusés, la neutralisation des restes d'interruption et l'expiration
    temporelle continuent de s'appliquer.**
25. **Les deux répertoires de spill ne sont pas le même** : `spill_guard` tombe dans `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` tombe dans `<workspace>/.flower/spill/` (qui doit être dans l'espace de travail).
26. **Le quatrième paramètre positionnel de `PruningSessionStore.__init__` est `prune`, pas `ephemeral`**,
    contrairement à la classe parente. Passer par position décale silencieusement les arguments.

### Documents et interaction {#陷阱-文书}

27. **Quand `Verdict` n'arrive pas à extraire une conclusion, `state=""` et `ok=False` : à ne surtout pas prendre pour un succès.**
    Par ailleurs « 无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable » sont tous classés en `unreachable`,
    ce qui déclenche la branche « on s'arrête et on demande à la personne », pas « on refait un tour ».
28. **`Brief.parse` jette tout ce qui suit une clôture de code fence manquante** — quand la sortie du modèle est
    tronquée, aucune des sections suivantes n'est parsée, `complete()` vaut `False`, et le gate renvoie l'étape à refaire.
29. **`Brief.load` traite `"(未填)"` comme vide.** Si vous éditez le brief à la main en recopiant le texte
    d'emplacement, cette section reste comptée comme manquante.
30. **Les trois sémantiques « 0 / None » de `HumanChannel` sont toutes différentes** : `max_asks=None` = illimité,
    `max_asks=0` = questions interdites ; `timeout_s=None` = attend indéfiniment, `timeout_s<=0` = timeout immédiat ;
    `remaining` renvoie **`-1`** quand `max_asks=None`.
31. **`Event("ask")` porte à la fois les questions et ce que la personne dit spontanément**, le second cas ayant
    `payload["kind"] == "mail"`. L'UI doit le tester d'abord.
32. **`Workflow.run` ne câble automatiquement que si `channel.on_event is None`** —
    si vous construisez vous-même `HumanChannel(on_event=...)`, les événements de question n'iront pas en même temps
    vers la sortie `on_event` du workflow.
