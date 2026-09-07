# API Python

Cette page épuise les **62 symboles publics** du `__all__` de premier niveau de `flower` : signatures, paramètres, valeurs par défaut, sémantique, attributs et méthodes publics. Après lecture, plus besoin d'ouvrir le source pour retrouver un paramètre.

L'organisation suit **ce qui vous intéresse**, pas le découpage en fichiers de modules — pour savoir « comment empêcher le [coordinateur](glossary.md#协调者) de mettre lui-même la main à la pâte », allez à la [couche hook](#hook) ; pour savoir « comment le résultat de l'étape précédente arrive à la suivante », allez au [workflow](#流程). La terminologie suit systématiquement le [glossaire](glossary.md).

Version `0.1.0`, dépendance `claude-agent-sdk>=0.2.152`. Toutes les signatures correspondent mot pour mot au source.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # un seul import de premier niveau
```

## Ce que contient cette page {#索引}

| Ce qui vous intéresse | Symboles |
|---|---|
| [Lancer un agent](#运行时) | `Runtime` `StepResult` |
| [Enchaîner plusieurs étapes](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Fabriquer un rôle](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Écrire une définition d'agent à la main](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documents structurés](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Intercepter des outils, élaguer des résultats, isoler](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Le répertoire de travail sur disque](#工作台) | `Workbench` |
| [Comment et quoi stocker des sessions](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Que faire quand le réseau tombe](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Remplacer l'UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Reprendre entre processus](#血缘) | `Lineage` |

## Six valeurs par défaut qui mordent {#危险默认值}

Ces six lignes ne sont pas des détails : ce sont les six accidents les plus fréquents. Chacune est expliquée en entier dans la section correspondante.

| Valeur par défaut | Conséquence | Détails |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | Les `Bash`/`Write`/`Edit` du thread principal n'ont **pas un seul hook** |[Runtime](#runtime) |
| `Runtime(handoff=True)` | Impose au spec un `CompactPolicy(mode="no_summary")`, c'est-à-dire `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Une étape avec `resume_from=None` reprend quand même la session de la dernière fois, entre processus | [Workflow](#workflow) |
| `build_options(fork=True)` sans `resume` | Échoue silencieusement, sans erreur | [build_options](#build-options) |
| `clarify(max_turns=<petit nombre>)` | Transforme « poser des questions sans limite de nombre » en parole vide — chaque question consomme un tour | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Portée session : interdit aussi aux subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Source : [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` est le cœur d'exécution. Il détient l'espace de travail, le [stockage de sessions](glossary.md#会话存储), le [workbench](glossary.md#工作台), la politique de [résilience](glossary.md#韧性) et la politique de [relève](glossary.md#换代), et n'expose qu'un seul verbe : `run` une étape. Les reprises, la continuation après interruption, la relève quand le contexte est plein — tout se passe dans cet appel unique.

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
| `workspace` | `str \| Path` | obligatoire | Le `cwd` de l'agent. Résolu à la construction puis `mkdir(parents=True, exist_ok=True)`. Le `project_key` du SDK en est dérivé — si le répertoire est déplacé ailleurs, les anciens `session_id` deviennent introuvables |
| `run_dir` | `str \| Path` | `"runs"` | Contient `sessions.db`, `manifest.json`, `lineage.json`, ainsi que le workbench par défaut quand `workbench=True`. Également résolu et créé |
| `portable` | `bool` | `True` | Transmis à `build_options(portable=)`, c'est-à-dire `setting_sources=[]` : ne lit ni le `~/.claude/` de la machine hôte, ni le `.claude/` du projet. Voir [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Une instance est utilisée telle quelle ; un `bool` donne `TrimPolicy(enabled=bool(trim))`. **Désactiver signifie seulement qu'on ne trimme pas les gros résultats ; l'élagage a quand même lieu** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Même règle de conversion. Va de pair avec `coordinator(glance=True)` — laisser le thread principal lancer `git status` suppose de garantir que ce résultat expirera |
| `keep_denials` | `int` | `1` | Transmis à `PrunePolicy(keep_denials=)`. Conserve les N derniers appels d'outil refusés ; les plus anciens sont retirés, appel et résultat ensemble |
| `workbench` | `Workbench \| bool` | `False` | Une instance est utilisée telle quelle ; `True` construit `Workbench(workspace, home=run_dir / "workbench")` (**par défaut hors de l'espace de travail**). Suivi immédiatement d'un `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | À partir de combien de caractères un résultat d'outil part en [spill](glossary.md#落盘). `None` ou `0` = pas de `spill_guard` installé |
| `resilience` | `Resilience \| bool` | `True` | Même règle de conversion |
| `handoff` | `HandoffPolicy \| bool` | `True` | Même règle de conversion |

**Le stockage de sessions est câblé en dur** : c'est toujours
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Les paramètres du constructeur **n'offrent pas** de point d'entrée pour changer de backend — pour en changer, construisez vous-même un `AgentSpec` + `build_options(session_store=...)`, ou écrasez `rt.store` après construction.

Les deux dernières étapes de la construction sont `load_dotenv()` et `check_credentials()`, et **la seconde `raise RuntimeError` en cas d'erreur**. Sans identifiants, l'explosion a lieu à la construction, pas au `run()`.

!!! warning "`workbench=False` + `coordinator()` = pas un seul mur devant le thread principal"
    `delegate_guard` n'est installé que dans `workbench_hooks`, et `workbench_hooks` n'est appelé que si `self.workbench is not None` ; `whitelist_guard`, lui, est sauté par `if not spec.delegate_only`. Or `coordinator()` fixe invariablement `delegate_only=True` et donne `Bash` par défaut via `glance=True`.

    **Conclusion : un coordinateur associé à `Runtime(workbench=False)` a ses `Bash`/`Write`/`Edit` interceptés par aucun hook.** Si vous utilisez `coordinator()`, activez le workbench — `Runtime(..., workbench=True)` ou passez une instance de `Workbench`.

!!! warning "`handoff=True` (défaut) désactive de force l'auto-compact"
    Dans `_attempt` : `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, ce qui donne `DISABLE_AUTO_COMPACT=1` dans le sous-processus. La raison : avec les deux mécanismes actifs en même temps, impossible de dire qui est responsable d'un retour du contexte à un niveau bas.

    **Le prix : l'étape qui écrit la relève doit avoir un chemin dégradé** (`handoff.degraded`), puisqu'il n'y a plus de compact en filet. Pour garder l'auto-compact, fournissez explicitement `AgentSpec.compact` (si le spec le fournit, il est respecté, pas écrasé).

#### Attributs publics {#runtime-属性}

| Attribut | Type | Description |
|---|---|---|
| `workspace` | `Path` | L'espace de travail après résolution |
| `run_dir` | `Path` | Le répertoire de run après résolution |
| `portable` | `bool` | Conservé tel quel |
| `store` | `PruningSessionStore` | Le stockage de sessions. Pour changer de backend, il faut l'écraser après construction |
| `resilience` | `Resilience` | L'instance après normalisation |
| `handoff` | `HandoffPolicy` | L'instance après normalisation |
| `workbench` | `Workbench \| None` | `None` quand `workbench=False` |
| `spill_threshold` | `int \| None` | Conservé tel quel, transmis à `workbench_hooks` dans `_attempt` |
| `results` | `list[StepResult]` | Chaque étape exécutée dans ce processus, ajoutée dans l'ordre |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Doit être unique par instance** — `manifest.json` déduplique sur le champ `run`, et si deux id se télescopent, le dernier à écrire supprimera la ligne de l'autre en la prenant pour la sienne |
| `on_session` | `Callable[[str], None] \| None` | Rappelé **immédiatement** à l'obtention d'un nouveau `session_id`, `None` par défaut. **Ne devrait couvrir que la ligne `runtime.run`** — si le [juge](glossary.md#判定者) utilise le même `Runtime` et que le callback est encore branché pendant la porte, la session du juge sera écrite dans le [lignage](glossary.md#血缘) de l'étape de travail |

Constantes de classe : `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`, `INTERRUPT_NOTE` (un paragraphe ajouté après les mots de l'humain lors de la reprise après interruption, expliquant que « les appels d'outil en vol qui renvoient interrupted sont un effet de bord normal de l'interruption, pas une panne d'environnement »).

#### Méthodes publiques {#runtime-方法}

| Méthode | Signature | Description |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Exécute une étape. Voir ci-dessous |
| `interrupt` | `(message: str = "") -> None` | Demande l'interruption du tour en cours. **Appelable depuis n'importe quel thread**. Coopératif : coupure propre à la **frontière d'un message**, pas d'annulation brutale. Chaîne vide = interrompre sans rien dire |
| `rescue` | `() -> None` | Solde les comptes autant que possible avant d'être tué brutalement ; appelé par les handlers `SIGHUP`/`SIGTERM`. L'étape en vol est aussi écrite dans le manifeste, avec `error="killed-by-signal"`. Ne fait que de petites écritures synchrones |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | Dans `str(workspace.resolve())`, tous les `/`, `_` et `.` sont remplacés par `-`. **Le SDK le dérive du cwd, l'appelant ne peut pas le fixer** |
| `has_session` | `(session_id: str) -> bool` | Cet id est-il encore trouvable sous **cet espace de travail** ? Synchrone, ne lit pas le payload |
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
| `step_name` | `str \| None` | `None` | La clé qui atterrit dans `StepResult.step`, le manifeste et le lignage. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Reprend ce `session_id` |
| `fork` | `bool` | `False` | Bifurque vers une nouvelle session sans polluer l'originale. **N'a d'effet que si `resume` est vrai** |
| `resume_at` | `str \| None` | `None` | Reprend à partir d'un message donné (rollback). Là aussi, **n'a d'effet que si `resume` est vrai** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie des événements, voir [`Event`](#event) |

Chaque étape commence par remettre à zéro le niveau de contexte (`self._ctx, self._warned = 0, False`). Vient ensuite une boucle avec quatre sorties :

1. **Succès** → on sort.
2. **Interruption humaine** (`result.error == INTERRUPTED`) → **non soumise à `max_attempts`**, n'attend pas le réseau. `resume` sur la même session avec les mots de l'humain, `attempt -= 1` (une interruption ne compte pas comme tentative échouée), prompt = mots de l'humain + `INTERRUPT_NOTE`. **Sans `session_id` obtenu, on ne peut que s'arrêter.**
3. **Contexte plein** (`result.error == HANDOFF_DUE`, ou bien `handoff.enabled` avec un `session_id` obtenu et `is_overflow(...)` qui déclenche) → **également non soumis à `max_attempts`**. On vérifie d'abord `len(result.retired) >= handoff.max_generations` ; si dépassé, l'erreur est remplacée par un diagnostic et on sort ; sinon on écrit le [document de relève](glossary.md#交接书) → `resume=None, fork=False` (**session entièrement neuve**) → le prompt devient `h.prompt_block()` → niveau de contexte remis à zéro → `attempt -= 1`.
4. **Panne reprenable** → on sort si `not resilience.enabled or attempt >= max_attempts` ; on sort aussi si `classify(error)` juge qu'il ne faut pas reprendre ; sinon on émet `Event("retry")`, on attend le réseau avec `wait_online()`, puis `sleep(delay_for(attempt))` ; **si un `session_id` a été obtenu, on reprend avec `resume`** (le prompt devient `resilience.resume_prompt`), et `result.resumed` est mis à `True`.

Clôture : écriture de `ended_at`, ajout à `self.results`, écriture de `manifest.json`.

`manifest.json` a une sémantique d'**ajout** : chaque écriture relit le disque et déduplique sur le champ `run` (sa propre ligne est remplacée, celles des autres sont conservées), donc faire tourner deux flower en parallèle sous le même `run_dir` est sûr — à condition que les `run_id` ne se télescopent pas.

**Les trois points d'observation de la relève** (tous des `Event("handoff")`, distingués par `payload["phase"]`) : `near` (approche de `warn_at`, émis une seule fois par génération), `writing` (la relève est en cours d'écriture, une dizaine de secondes), `done` (payload avec `degraded` / `path` / `sections`). Le tour qui écrit la relève tourne avec `replace(spec, max_budget_usd=None)` — la relève doit pouvoir être écrite, elle ne peut pas rester bloquée sur le budget ; et `on_event=None`, ce tour ne remonte rien à l'UI.

La relève est écrite dans `<workbench.notes>/交接-<步骤名>.md` ; **sans workbench, rien n'est écrit sur disque**, le document est tout de même remis au successeur via le prompt, il est simplement introuvable après coup. Les anciennes relèves sont déplacées vers `notes/archive/交接/<名>-<时间戳>.md`.

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

Tous les comptes d'une étape terminée.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `step` | `str` | obligatoire | Nom de l'étape (`step_name` ou `spec.name`) |
| `session_id` | `str \| None` | `None` | **Toujours la dernière session à avoir pris la suite** — celles brûlées par les relèves intermédiaires sont dans `retired` |
| `ok` | `bool` | `False` | Cette étape a-t-elle réussi |
| `cost_usd` | `float` | `0.0` | En dollars. **Cumulé** à travers les reprises et les relèves |
| `num_turns` | `int` | `0` | Nombre de tours, également cumulé |
| `text` | `str` | `""` | **Ne contient que le corps du thread principal**. Les prises de parole d'un subagent restent dans son propre transcript, et le brief de tâche qui lui est délégué est de `kind="prompt"` : ni l'un ni l'autre n'y entrent |
| `error` | `str \| None` | `None` | Cause de l'échec. Valeurs spéciales : voir `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Nombre réel de tentatives. Interruptions et relèves **ne comptent pas** |
| `errors` | `list[str]` | `[]` | Les messages d'erreur d'API synthétiques collectés, **n'entrent pas dans `text`** |
| `resumed` | `bool` | `False` | Y a-t-il eu une reprise par `resume` en cours de route |
| `retired` | `list[str]` | `[]` | Les `session_id` brûlés par les relèves de cette étape, dans l'ordre |
| `context` | `int` | `0` | La taille de contexte réellement vue par le thread principal au dernier tour, c'est-à-dire le critère de relève |

| Attribut | Type | Description |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, `0.0` si pas terminé |

---

## Workflow {#流程}

Source : [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Un [workflow](glossary.md#流程) est un ensemble d'[étapes](glossary.md#步骤) enchaînées dans l'ordre,
plus la façon dont l'état circule entre elles et le moment où l'on sort par anticipation.
**Le framework ne fournit aucun workflow tout fait : le workflow, c'est vous qui l'écrivez** —
`starter_flow` n'est qu'un modèle qui tourne.

Alias de type `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, présent dans `flower.workflow.__all__`,
pas dans le `__all__` de premier niveau).

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

La **déclaration** d'une étape. `Step` n'est pas une fonction — ce qui s'exécute réellement, c'est
`Runtime.run(step.spec, prompt, ...)`. Les trois premiers champs sont positionnels :
`Step("取词", terse, "读 seed.txt …")` est une écriture valide.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom de l'étape. **Clé stable entre processus** — elle atterrit dans `ctx[name]`, `ctx["_results"]`, le manifeste et la lignée. Renommer = casser la lignée |
| `spec` | `AgentSpec` | requis | Quel agent exécuter |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | Quoi dire. Peut être une closure, calculée à partir de `ctx` |
| `resume_from` | `str \| None` | `None` | Quelle session d'étape reprendre. Si l'étape visée n'a produit aucune session, **lève `ValueError`** — pas de saut silencieux |
| `fork` | `bool` | `False` | Fork à partir de `resume_from`. **Sans `resume_from`, sans effet** |
| `retries` | `int` | `0` | Nombre d'essais supplémentaires quand le gate ne passe pas. `retries=0` = un seul tour |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Décide si cette tentative passe. **Peut être async**. Renvoyer `False` vaut échec. **Appelé une seule fois par tentative** — il peut avoir des effets de bord (écrire le brief sur disque, par exemple) et ne doit pas être déclenché deux fois |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, voir plus bas |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Renvoyer `False` **saute toute l'étape** : aucun result produit, rien dans `ctx["_results"]`. **Peut être async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Ce qu'on dit **au tour suivant** quand le gate ne passe pas. **Peut être async**. Le fournir change la sémantique du retry, voir plus bas |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt utilisé en reprise (plutôt qu'un départ de zéro) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Décide ce qui va dans `ctx[name]`. Par défaut, le texte brut `result.text`. **Doit être une fonction synchrone** |

| Méthode | Signature | Description |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Si `resuming` et qu'un `resume_prompt` existe, c'est ce dernier, sinon `prompt` ; si c'est un callable, il est appelé avec `ctx` |

**Trois façons de raccorder les sessions** (au sein d'un même run) :

| Écriture | Effet |
|---|---|
| `resume_from=None` (défaut) | Nouvelle session, avec pour seul contexte ce que le prompt transmet. Bon marché, isolé. **Mais avec `Workflow(continuous=True)`, la session de l'étape du même nom est reprise depuis la lignée inter-processus** |
| `resume_from="上一步名"` | Reprend la même session, contexte complet. Cher, cohérent |
| `resume_from="上一步名", fork=True` | Fork, sans polluer la session d'origine. Pour la relecture / plusieurs pistes en parallèle |

**`on_reject` change la sémantique du retry** :

- Non fourni → la tentative suivante **repart de zéro** (même prompt, même `resume_from`).
- Fourni → la tentative suivante **reprend la session qui vient d'être rejetée**, le prompt devient sa valeur de retour, et `fork` est forcé à `False`.
- Renvoie une chaîne vide → pas de renvoi, on retombe sur un départ de zéro.
- `result.session_id` vaut `None` → on retombe aussi sur un départ de zéro.

**Les trois valeurs de `on_fail`** :

| Valeur | Comportement |
|---|---|
| `"stop"` (défaut) | Écrit `ctx["_failed_at"] = name`, **interrompt tout le workflow** |
| `"skip"` | Passe à l'étape suivante, **`ctx[name]` n'est pas écrit** — un `lambda ctx: ctx["某步"]` en aval lèvera `KeyError` |
| `"continue"` | `ctx[name] = result.text`, on avance avec un résultat incomplet |

Que ça passe ou non, `ctx["_results"][name] = result` est toujours écrit ; si `result.session_id` est
non vide, il est aussi écrit dans `ctx["_sessions"]` avec un `lineage.remember(...)`.

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
| `context` | `Ctx` | `{}` | Dictionnaire de contexte initial. **Au second run d'un même `Workflow`, c'est le même dict** |
| `channel` | `HumanChannel \| None` | `None` | À brancher ici quand il faut s'arrêter pour interroger un humain. `run()` raccorde automatiquement son `on_event` à la même sortie, **uniquement si `channel.on_event is None`** ; c'est aussi par ce champ que le driver sait à qui répondre |
| `workbench` | `Workbench \| None` | `None` | Le workbench désigné par le workflow, pour que le driver le trouve |
| `continuous` | `bool` | `True` | Même chemin = même conversation. Implémenté par [`Lineage`](#lineage) |

| Paramètres de `run()` | Type | Défaut | Description |
|---|---|---|---|
| `runtime` | `Runtime` | requis, positionnel | Avec quel runtime exécuter |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Sortie d'événements, transmise telle quelle à chaque `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Rappelé une fois à la fin de chaque étape |

!!! warning "`continuous=True` est le défaut, `resume_from=None` ne veut pas dire session neuve"
    Quand la continuité est active, `run()` commence par `Lineage.open(run_dir, workspace)`, puis
    vérifie chaque enregistrement avec `runtime.has_session(sid)` pour savoir s'il est toujours dans
    le store ; seules les sessions vivantes sont injectées dans `ctx["_sessions"]`. Résultat :
    **une étape avec `resume_from=None` parle elle aussi dans la session de la dernière fois** —
    même après un processus tué ou un redémarrage de la machine.

    Pour avoir une session neuve à chaque fois, écrivez explicitement `Workflow(..., continuous=False)`.
    Par ailleurs : **le nom d'étape est une clé stable entre processus ; le changer revient à couper la lignée.**

Les **clés privées** que `run()` écrit dans ctx (toutes préfixées par `_`, aucune collision possible
avec un nom d'étape) :

| Clé | Contenu |
|---|---|
| `_runtime` | Le `Runtime` passé en argument. **C'est par lui qu'un gate lance un agent** |
| `_on_event` | La sortie d'événements. L'agent lancé dans un gate doit aussi pouvoir atteindre l'UI, sinon l'interface reste noire |
| `_sessions` | `dict[nom d'étape, session_id]`, lu via `setdefault` |
| `_results` | `dict[nom d'étape, StepResult]` |
| `_lineage` | L'objet `Lineage`. Présent uniquement si `continuous=True` et que le runtime a un `run_dir` + un `workspace` |
| `_woke` | La valeur de retour de `lineage.bump()`, le numéro du réveil courant |
| `_aborted` | Le message du `StepAbort` |
| `_failed_at` | Le nom de l'étape en échec avec `on_fail="stop"` |

Payload de `Event("step")` : `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Étiquettes de retry** : la tentative 0 utilise `step.name` ; ensuite, avec `on_reject`,
`f"{name}#round{attempt+1}"`, sinon `f"{name}#retry{attempt}"`. Le manifeste montre d'un coup d'œil
comment l'étape s'est terminée.
**Les noms suffixés n'entrent pas dans la lignée inter-processus** — `Lineage.remember` utilise le nom d'origine.

`runtime.on_session` ne couvre que l'appel `runtime.run` ; un `try/finally` garantit qu'il est retiré
avant le gate. `prompt_cur` / `resume_cur` / `fork_cur` sont des variables locales, jamais réécrites
dans `step` — le même objet `Step` peut être exécuté une seconde fois.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Levée par le `gate` = **arrêt immédiat, aucun nouvel essai**. Différence avec « renvoyer `False` » :
`False` veut dire « pas cette fois, encore un tour » ; `StepAbort` veut dire « recommencer ne servira à rien ».

Après la levée : `ctx["_aborted"] = str(exc)`, `passed = False`, **sortie de la boucle de retry
(les `retries` restants ne sont pas consommés)**, puis traitement comme un échec ordinaire via
`on_fail` (`"stop"` par défaut).

`with_goal` la lève à deux endroits : quand `ctx["_runtime"]` est introuvable, et quand le verdict est
`unreachable` sans que personne ne réponde.

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

Produit un `Step` de [clarification préalable](glossary.md#前置确认) : questionner jusqu'à ce que le
besoin soit clair → parser en [`Brief`](#brief) → si les quatre sections sont complètes, geler et écrire sur disque.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Canal de questions |
| `brief_path` | `str \| Path` | requis | Où atterrit le [brief](glossary.md#需求确认书). **Doit être dans le workbench dont l'index est réellement injecté** |
| `prompt` | `str \| Callable[[Ctx], str]` | requis | La demande brute de l'humain |
| `name` | `str` | `"确认需求"` | Nom de l'étape, et en même temps clé dans `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Sans valeur, on utilise `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions complémentaires ajoutées au [clarificateur](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = reposer les questions à chaque fois, que le brief existe ou non |
| `on_fail` | `str` | `"stop"` | Comme `Step.on_fail` |
| `retries` | `int` | `0` | Combien de fois redemander quand les quatre sections ne sont pas réunies |
| `**spec_kw` | | | Transmis tel quel à [`clarify()`](#clarify-role), donc on peut écrire `can_read=False`, `max_budget_usd=...` |

Les champs du `Step` produit sont remplis ainsi :

- `resume_prompt = CLARIFY_RESUME`.
- `when` : si `always_ask=True` → toujours `True` ; sinon, si `Brief.load(brief_path)` est complet, il
  est injecté dans ctx **puis on renvoie `False` (étape sautée)** — il faut injecter même en sautant,
  sinon l'aval n'a pas le besoin.
- `gate` : `Brief.parse(result.text)` ; incomplet → écrit `ctx[MISSING_KEY]` et renvoie `False` ;
  complet → `b.write(brief_path)` pour geler, injection dans ctx, renvoie `True`.
- `reduce` : renvoie `ctx[BRIEF_KEY].prompt_block()`, **pas le texte brut du modèle** — celui-ci peut
  contenir ce qu'il a écrit en trop.
- `resume_from` **reste à `None` par défaut** : l'étape suivante est une nouvelle session, elle n'obtient
  que le brief, pas les questions-réponses. Les questions-réponses de la clarification préalable
  **ne sont jamais entrées** dans le contexte du coordinateur ; elles n'y ont pas été taillées après coup.

Trois injections dans ctx : `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Constante | Valeur | Description |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` est un objet `Brief` ; `ctx[step.name]` est son `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Quelles sections manquent quand la clarification échoue (noms de sections en chinois), pour affichage dans l'UI |
| `CLARIFY_RESUME` | un prompt en chinois | « 接着刚才那次没问完的需求确认继续 —— **不是重新开始**…… ». Sans cette phrase, la reprise renvoie la demande initiale comme une nouvelle tâche, et le clarificateur risque de reposer les questions déjà posées |

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

Produit un `Step` qui **fixe l'objectif** : le [juge](glossary.md#判定者) lit le brief, écrit l'objectif
et sa liste de contrôle, le tout est parsé en [`Goal`](#goal), gelé et écrit sur disque. Même forme que
`clarify_step`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | requis, positionnel | Canal de questions |
| `goal_path` | `str \| Path` | requis | Où atterrit le fichier d'objectif |
| `brief_key` | `str` | `"确认需求"` | Le texte du brief est pris dans `ctx[brief_key]` et injecté dans le prompt. **S'il est introuvable, c'est `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nom de l'étape |
| `spec` | `AgentSpec \| None` | `None` | Sans valeur, on utilise `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instructions supplémentaires |
| `always_set` | `bool` | `False` | `True` = recalculer la liste, que le fichier d'objectif existe ou non |
| `on_fail` | `str` | `"stop"` | Idem ci-dessus |
| `retries` | `int` | `0` | Idem ci-dessus |
| `**spec_kw` | | | Transmis à [`judge()`](#judge-role) |

**Pas de paramètre `can_run`** — pour que le juge qui fixe l'objectif puisse lancer des commandes, il
faut passer `can_run=True` via `**spec_kw`. Sans cela il n'a pas `Bash`, et la règle
« 先看清楚你在什么环境 » de `JUDGE_RULES` est inapplicable.

Au-delà du parsing et du gel, le `gate` fait une chose de plus : si l'objectif contient des entrées
`[此环境无法验证:…]`, il émet **sur-le-champ**, via `ctx["_on_event"]`, un
`Event("task", payload={"unverifiable", "total", "path"})` en guise d'alerte — le sort de ces entrées
est scellé à l'instant où l'objectif est fixé ; au moment du verdict, on a déjà dépensé un tour de
travail complet.

**Pas de `resume_prompt`** — fixer l'objectif doit de toute façon renvoyer le brief en entier.

| Constante | Valeur | Description |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` est un objet `Goal` ; `ctx[step.name]` est du markdown |
| `VERDICT_KEY` | `"_verdict"` | Le dernier [`Verdict`](#verdict), pour l'UI |
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

Ajoute une [garde d'objectif](glossary.md#目标看守) à un `Step` existant : à la fin de chaque tour, le
juge statue de façon indépendante ; si l'objectif n'est pas atteint, l'étape est renvoyée pour continuer.

Le résultat est `replace(step, retries=max(0, rounds - 1), gate=<nouveau gate>, on_reject=<nouveau on_reject>)` —
avec `dataclasses.replace` plutôt qu'une reconstruction champ par champ : une reconstruction a déjà
oublié `resume_prompt` une fois, **sans lever la moindre erreur**, elle se contentait de renvoyer le
brief en entier à chaque reprise.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `step` | `Step` | requis, positionnel | L'étape gardée |
| `channel` | `HumanChannel` | requis, positionnel | Canal pour demander de l'aide à un humain quand le verdict est bloqué |
| `goal_path` | `str \| Path` | requis | Fichier d'objectif, lu ici quand `ctx[GOAL_KEY]` est incomplet |
| `spec` | `AgentSpec \| None` | `None` | Sans valeur, on utilise `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Nombre total de tours, pas de tours supplémentaires** : `rounds=3` → `retries=2` → au plus trois tours de travail. `rounds=1` = un tour, un verdict, échec s'il ne passe pas |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le juge |
| `can_run` | `bool` | `False` | Le juge peut-il lancer `Bash` |
| `name` | `str \| None` | `None` | Nom du juge, par défaut `f"{step.name}·判定"` |
| `**spec_kw` | | | Transmis à `judge()` |

Le `gate` est **async**, déroulé :

1. `ctx["_runtime"]` manquant → **lève `StepAbort`** (« 拿不到 Runtime,无法判定目标 »). **Ne fais pas semblant que ça passe.**
2. `ctx[ROUND_KEY] += 1`.
3. Récupération de l'objectif : en priorité un `Goal` complet dans `ctx[GOAL_KEY]`, sinon `Goal.load(goal_path)`, sinon un `Goal()` vide.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Le juge est un `Runtime.run` indépendant, `resume` vaut toujours `None` — c'est toujours une
   nouvelle session** ; `step_name` porte le numéro de tour, donc il n'entre pas dans la lignée inter-processus.
5. `Verdict.parse(vr.text)` est écrit dans `ctx[VERDICT_KEY]`.
6. `v.achieved` → renvoie `True`.
7. Pas `unreachable` (y compris les cas ambigus avec `v.ok=False`) → en cas d'ambiguïté, une raison par
   défaut est ajoutée, et on renvoie `False`. **Toute ambiguïté compte comme non atteint** — on ne
   laisse pas un « ça a l'air bon » clore le travail.
8. `unreachable` → `await channel.ask(...)` pour interroger l'humain, trois options :
   - Personne ne répond (`a.state != "answered"`) → **lève `StepAbort`**. Continuer à tourner à vide est l'option la plus coûteuse.
   - « 接受这个结果,就这样往下走 » → renvoie `True`.
   - « 修改目标 » → nouvelle question pour obtenir le nouvel objectif, `g.amend(...).write(goal_path)`, mise à jour de `ctx[GOAL_KEY]`, renvoie `False`.
   - Tout le reste (y compris une réponse libre tapée par l'humain) → traité comme « tu t'es trompé dans ton jugement » : la formulation de l'humain est consignée dans `v.reason`, renvoie `False`.

`on_reject` est **synchrone** : il renvoie `ctx[VERDICT_KEY].feedback()`, ou `""` s'il n'y a pas de
`Verdict` (on retombe sur un départ de zéro).

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

Assemble un workflow en trois étapes utilisable tel quel : **confirmer le besoin → fixer l'objectif →
travailler** (avec garde d'objectif). C'est exactement ce qu'utilise la ligne de commande `flower`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `ask` | `str` | requis, positionnel | Une phrase de demande. **Lors d'un réveil, ce n'est pas une nouvelle tâche, c'est « une phrase de plus »** |
| `workspace` | `str \| Path` | `"."` | Espace de travail |
| `run_dir` | `str \| Path` | `"runs"` | Répertoire du run |
| `new` | `bool` | `False` | `True` = archive la lignée + le brief + l'objectif (les trois d'un coup) et repart de zéro |
| `isolate` | `bool` | `False` | Ouvre un worktree d'[isolation](glossary.md#隔离) pour l'exécutant. Le workbench se déplace en conséquence vers `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Ne renvoie que le Workflow contenant l'étape de clarification |
| `goal` | `bool` | `True` | Installer ou non la [garde d'objectif](glossary.md#目标看守). `False` = une fois l'étape de travail terminée, c'est fini |
| `rounds` | `int` | `3` | Transmis à `with_goal(rounds=)`, nombre total de tours |
| `judge_can_run` | `bool` | `False` | Transmis à `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Transmis à `HumanChannel`, `None` = pas de limite |
| `timeout_s` | `float \| None` | `1800.0` | Transmis à `HumanChannel`. `0` = tout automatique, toute question tombe immédiatement à vide |
| `instructions` | `str` | `""` | Instructions supplémentaires pour le clarificateur |
| `worker_prompt` | `str` | voir la signature | System prompt de l'exécutant |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier de brief, écrit dans `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier d'objectif, même emplacement |
| `log_name` | `str` | `"问答记录.md"` | Nom du fichier de journal des questions-réponses, même emplacement |

Assemblage fixe :

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Branches de comportement :

- `isolate=True` et workspace qui n'est pas un dépôt git → **lève `ValueError`**, sans attendre que
  l'outil `Agent` remonte l'erreur (à ce moment-là l'argent est déjà dépensé).
- **Détection du réveil** : si `Brief.load(brief_path)` existe et que `complete()` est vrai, c'est un
  réveil. Si ce n'est pas un réveil et que `ask` est vide →
  **lève `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Lors d'un réveil, cette phrase atterrit à **trois endroits** ; s'il en manque un, elle échoue
  silencieusement : ajoutée au brief
  (`ch.amend(said, label="唤醒时追加")`, pas de réécriture si elle y figure déjà) ;
  `goal_step(always_set=True)` pour recalculer la liste (sans quoi le juge lit encore l'ancien objectif) ;
  envoyée directement au coordinateur (son contexte contient l'**ancien** objectif ; sans elle, il
  travaille selon l'ancien critère puis est jugé selon le nouveau).

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

**Sonde en lecture seule avant le démarrage : n'écrit pas un seul octet.** Sert à dire à l'humain,
avant de lancer pour de bon, s'il s'agit d'une reprise ou d'un départ de zéro.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Espace de travail, positionnel |
| `run_dir` | `str \| Path` | `"runs"` | Répertoire du run |
| `isolate` | `bool` | `False` | Détermine l'emplacement du workbench, doit valoir la même chose que ce qui est passé à `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nom du fichier de brief |
| `goal_name` | `str` | `"目标.md"` | Nom du fichier d'objectif |

Le dict renvoyé :

| Clé | Type | Description |
|---|---|---|
| `waking` | `bool` | Le brief existe et ses quatre sections sont complètes |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Nombre d'entrées de la liste de l'objectif, `0` s'il n'y a pas d'objectif |
| `woke` | `int` | `Lineage.woke`, nombre de réveils déjà effectués |
| `steps` | `dict` | Copie de `Lineage.steps`, nom d'étape → `session_id` |

L'emplacement du workbench **n'est défini qu'ici et dans `starter_flow`** : `isolate=True` →
`<ws>.parent/.flower-<ws.name>` (hors du dépôt) ; sinon `<ws>/.flower`. Un driver qui veut savoir où
se trouve le brief passe aussi par cette fonction — reconstruire le chemin à la main ne lève aucune
erreur, ça échoue simplement en silence.

---

## Fabrique de rôles {#角色工厂}

Source : [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Les cinq rôles sont tous des fonctions fabriques. Chaque rôle = **un bloc de règles injecté + un jeu d'outils + un jeu de hooks**.
`worker()` produit un `AgentDefinition` du SDK (destiné à être délégué à un subagent), les quatre autres produisent un [`AgentSpec`](#agentspec)
(qui ouvre sa propre session).

Les rôles eux-mêmes **n'attachent aucun hook** — l'interception des outils est montée automatiquement par `Runtime._attempt` selon `spec.delegate_only`,
voir [la couche hook](#hook).

Constantes internes de jeux d'outils (non exportées, mais elles déterminent les valeurs par défaut) :

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

Fabrique le [coordinateur](glossary.md#协调者) qui tourne sur le [thread principal](glossary.md#主线程) : il découpe la tâche, délègue, lit les rapports, décide,
**mais ne met pas la main à la pâte**. Les trois premiers paramètres sont positionnels.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du rôle, aussi le nom de step par défaut |
| `instructions` | `str` | requis | Instructions métier. Au final `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | requis | Les rôles sous ses ordres, transmis à `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Si fourni, ajoute **à la fois** les outils `inbox` **et** `ask`, et renseigne `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]` ; `False` → sans `Read` |
| `glance` | `bool` | `True` | Ajoute `"Bash"` et renseigne `AgentSpec.glance`. **Ce qui peut réellement s'exécuter est filtré par `delegate_guard`**, pas ici |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Mode de permission. **Attention à cette valeur par défaut** — la passer à `clarify()`/`judge()` démonte la protection de ces deux rôles |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, `Runtime` ne le forcera pas à `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks additionnels, fusionnés avec `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variables d'environnement additionnelles |

Trois champs fixés dans l'`AgentSpec` produit : `delegate_only=True`, `agents=workers`,
et `workbench` garde le `True` par défaut d'`AgentSpec`.

Le code source dit explicitement de **ne pas utiliser `disallowed_tools` pour obtenir « coordonner sans agir »** — c'est au niveau de la session,
cela désactiverait aussi `Bash`/`Write` chez les subagents, voir l'avertissement dans [`AgentSpec`](#agentspec).
La bonne méthode est celle d'ici : `delegate_only=True` + ne rien mettre dans `allowed_tools`,
puis laisser [`delegate_guard`](#delegate-guard) n'intercepter que le thread principal via `agent_id`.

Fournir `channel` amène **les deux outils ensemble**, ce n'est pas optionnel : dès que le serveur MCP est monté, les deux sont là, et
`allowed_tools` n'étant pas exclusif, ils sont appelables qu'ils y figurent ou non. En mode sans surveillance, chaque `ask` bloquera jusqu'au bout du `timeout_s` —
dans ce cas, utilisez `HumanChannel(timeout_s=0)`.

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
Le retour est un `AgentDefinition` du SDK, à mettre directement dans `coordinator(workers={...})`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `description` | `str` | requis | **La base sur laquelle le coordinateur choisit** — écrivez clairement « quel travail lui confier » |
| `prompt` | `str` | requis | Son system prompt. Avec `discipline=True`, devient `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Un worker ne doit pas être rétrogradé |
| `effort` | `str \| int \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Transmis au **`maxTurns`** du SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Transmis au **`permissionMode`** du SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Quelles skills il a le droit d'utiliser |
| `discipline` | `bool` | `True` | Concaténer ou non le bloc de discipline de rapport `WORKER_RULES` |
| `isolate` | `bool` | `False` | Pose la marque d'[isolation](glossary.md#隔离), passe par `isolated()`, **ce n'est pas un champ d'`AgentDefinition`** |

`isolate=True` exige que le workspace soit un dépôt git, sinon l'outil `Agent` renvoie directement `"not in a git repository"`,
**il n'y a pas de dégradation silencieuse**. De plus, la marque est un attribut Python — faire un `dataclasses.replace()` sur l'`AgentDefinition`
la perd, et l'isolation cesse silencieusement d'être active.

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

Fabrique le [clarificateur](glossary.md#确认者) : avant d'agir, il tire au clair le besoin ; il ne fait rien, il pose seulement des questions, et produit à la fin exactement quatre sections.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | requis | Nom du rôle, positionnel |
| `channel` | `HumanChannel` | requis | Canal de questions, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Si `True`, ajoute `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | **Nombre de tours illimité** |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produit : `allowed_tools = [channel.tool_name] + (les cinq ci-dessus si lecture autorisée)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (il n'a pas d'outil d'écriture, l'index ne lui sert à rien),
`permission_mode` hérite du `"default"` par défaut d'`AgentSpec`.
**Ni `Write`, ni `Edit`, ni `Bash`, ni `Agent`, et pas d'`inbox` non plus** (contrairement au coordinateur).

!!! warning "Un `max_turns` petit rend creuse la promesse de questions illimitées"
    Chaque question consomme un tour. `max_turns=16` équivaut à « une douzaine de questions au maximum », et la phrase du canal « pas de plafond de tours » devient caduque sur-le-champ.

    Pour vraiment libérer le questionnement, il faut libérer **les deux** : `HumanChannel.max_asks` (déjà `None` par défaut = illimité)
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
| `name` | `str` | requis | Nom du rôle, positionnel |
| `channel` | `HumanChannel` | requis | Canal de questions, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Si `True`, ajoute `Bash` à la liste blanche ; `whitelist_guard` laisse alors passer `Bash` mais bloque toujours `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de budget |

L'`AgentSpec` produit : `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (si `can_run`) `["Bash"]`,
`workbench=False`, le reste comme `clarify()`. **Ni `Write`, ni `Edit`, ni `Agent`, et pas d'`inbox`.**

**Arbitrage** : `can_run=True` rend le verdict plus dur (il peut réellement exécuter les commandes de recette), au prix de donner au juge la capacité de modifier l'espace de travail —
`Bash` permet en soi d'écrire des fichiers. Pour un verdict absolument neutre, ne l'activez pas.

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

Fabrique l'[oracle](glossary.md#旁路顾问) : pendant qu'un run est encore en cours, vous lui demandez « où en est-on ? » ; il jette un œil aux événements récents et à l'établi
avant de répondre. **Ce qu'il dit n'entre pas dans le contexte de ce run.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nom du rôle, positionnel |
| `instructions` | `str` | `""` | Instructions complémentaires, concaténées après `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | **`12`** | Vanne active par défaut |
| `max_budget_usd` | `float \| None` | **`0.5`** | Vanne active par défaut. C'est « une question en passant », ça ne doit pas déraper |

L'`AgentSpec` produit : `allowed_tools = ["Read", "Glob", "Grep"]` (**pas de channel** — il ne pose pas de questions,
il y répond), `workbench=True` (**le seul des cinq rôles à activer l'établi sans être coordinateur** — c'est justement pour aller lire ces productions et ces notes).

### Les cinq blocs de règles {#rules}

Les cinq constantes sont dans `__all__` : vous pouvez les `import`er pour les lire, les composer, les modifier.

| Constante | Injectée dans | Mode d'injection | Points clés |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Tu es « quelqu'un qui sait se servir de Claude Code », pas un worker ; interdit d'écrire des fichiers/modifier du code/lancer des tests ; `Bash` ne sert qu'à « jeter un œil » et le résultat périmera ; **le [cahier de tâche](glossary.md#任务书) ne contient que ce qui est propre à cette tâche** ; la seule règle qu'il reste à transmettre est « où est l'établi + les longues productions vont dans `artifacts/` + ne renvoyer que des chemins » ; consulter `inbox` après chaque action d'étape ; `ask` bloque, à n'utiliser qu'aux vrais carrefours |
| `WORKER_RULES` | `worker()` | Concaténé **après** le `prompt` du subagent | Format de réponse **conclusion / justification / production / non vérifié**, pas plus de 30 lignes ; interdit de coller le contenu de fichiers, sorties de commandes, logs, diffs bruts ; interdit de raconter les tâtonnements ; regarder `.flower/scripts/` avant d'agir. **N'indique volontairement pas « les longues productions vont dans `artifacts/` »** — le chemin réel est généré par `Workbench`, le figer serait faux |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Ne fait rien, se contente de clarifier le besoin ; **pas de limite de nombre, on questionne jusqu'à ce que ce soit clair** ; l'humain peut être absent, en cas de timeout tranche toi-même et consigne-le dans « Inconnues et hypothèses » ; sortie en **exactement quatre sections** ; ne pas écrire de code, ne pas coller de contenu de fichiers |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Deux missions au choix. **Fixer l'objectif** : chaque item de la liste doit être vérifiable sur-le-champ, la longueur de la liste est dictée par le nombre de modes de défaillance, **les limites ne sont pas des items de verdict**, les items non vérifiables se terminent par `[此环境无法验证:原因]`. **Juger le tour** : sortie en **exactement trois sections**, on juge **la production, pas le code source**, on ne croit pas « c'est fini » par défaut, « non atteint » et « invérifiable ici » sont deux conclusions différentes, et la seconde **n'autorise absolument pas un verdict de réussite** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Tu es une voie de dérivation ; ce run tourne encore, tu ne l'interromps pas et tu n'y participes pas ; **lecture seule** ; jetable après réponse, ce que tu dis n'entrera pas dans le contexte de ce run ; tu ne disposes que de « la fenêtre d'événements récents » et de « l'établi » ; regarde avant de répondre, dis que tu ne peux pas si tu ne peux pas, sois bref |

---

## Définition d'agent {#agent-定义}

Source : [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` est la déclaration complète d'un agent spécialisé, et `build_options` la compile en `ClaudeAgentOptions` du SDK.
C'est précisément ce que produit la [fabrique de rôles](#角色工厂) — si vous avez besoin d'une combinaison hors fabrique, construisez-le directement.

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
| `name` | `str` | requis | Nom du rôle. Aussi le `step_name` par défaut de `Runtime.run`, et la façon dont il se désigne dans le message de refus de `whitelist_guard` |
| `instructions` | `str` | requis | Instructions métier. **[Ajoutées](glossary.md#叠加) après le system prompt natif de Claude Code, elles ne le remplacent pas** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Liste de dispense d'approbation, pas une liste blanche exclusive** — le modèle peut toujours appeler des outils qui n'y figurent pas. L'exclusivité passe par [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Niveau session**. Voir l'avertissement ci-dessous |
| `model` | `str \| None` | `None` | Modèle |
| `effort` | `str \| None` | `None` | Intensité de réflexion |
| `max_turns` | `int \| None` | `None` | Plafond de tours |
| `max_budget_usd` | `float \| None` | `None` | Plafond de [budget](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Mode de permission |
| `agents` | `dict[str, Any] \| None` | `None` | Table des définitions de subagents, valeurs de type `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Table des serveurs MCP. `HumanChannel.mcp_servers()` la remplit directement |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks additionnels, que `Runtime` fusionne avec les siens via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Si fourni, `Runtime` ne le forcera pas à `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variables d'environnement injectées dans le sous-processus. `compact.env()` viendra les mettre à jour |
| `glance` | `bool` | `False` | Autorise le coordinateur à lancer lui-même des `Bash` « pour jeter un œil ». Ce qui passe est décidé par [`is_ephemeral`](#is-ephemeral), et le résultat sera marqué comme périmé par `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Injecter ou non l'index de l'établi dans le system prompt de cet agent. **À désactiver pour les rôles sans outil d'écriture** (`clarify()` / `judge()` sont déjà à `False`) |
| `delegate_only` | `bool` | `False` | Coordonner sans agir. Si `True`, `Runtime` monte `delegate_guard` et **ne monte pas** `whitelist_guard` |

!!! warning "`disallowed_tools` est au niveau de la session et désactive aussi les subagents"
    Message d'erreur constaté en pratique : `"Bash is disabled for this session, in subagents as well as here"`.
    Autrement dit, si vous utilisez `disallowed_tools=["Bash"]` pour empêcher le coordinateur d'agir, les workers délégués ne peuvent plus exécuter de commandes non plus —
    tout le run est fichu.

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

Compile un `AgentSpec` en `ClaudeAgentOptions` du SDK. C'est ce qu'appelle `Runtime._attempt` en interne ;
c'est aussi le point d'entrée si vous pilotez le SDK vous-même (sans `Runtime`).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | requis, positionnel | La déclaration à compiler |
| `cwd` | `str \| Path \| None` | `None` | N'écrit `cwd` que si non-`None` |
| `session_store` | `SessionStore \| None` | `None` | N'écrit `session_store` et `session_store_flush` que si non-`None` |
| `resume` | `str \| None` | `None` | Quelle session reprendre |
| `fork` | `bool` | `False` | Devient `fork_session`. **Imbriqué dans `if resume:`** |
| `resume_at` | `str \| None` | `None` | Devient `resume_session_at`. **Également imbriqué dans `if resume:`** |
| `use_plugin` | `bool` | `True` | Si `True` et que `PLUGIN_DIR` existe → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]` ; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Répertoires autorisés en plus. **Obligatoire quand l'établi est hors de l'espace de travail** |
| `flush` | `str` | `"eager"` | Devient `session_store_flush` |
| `prelude` | `str` | `""` | Bloc ajouté après `instructions` (c'est par là que passe l'index de l'établi) |

Correspondances :

| Clé d'option produite | Valeur |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Repris tels quels de `spec` |
| `setting_sources` | `[]` (portable) ou `["project"]` |
| `plugins` | Présent uniquement si le répertoire `plugin/` à la racine du dépôt existe |
| `cwd` / `add_dirs` | Écrits seulement si non vides |
| `session_store` / `session_store_flush` | Écrits seulement si `session_store` est non-`None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Chacun écrit seulement s'il est non vide |
| `env` | `dict(spec.env)` puis `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **N'entrent en vigueur que si `resume` est vrai** |

`PLUGIN_DIR` est le répertoire `plugin/` à la racine du dépôt (trois niveaux au-dessus de `flower/core/agent.py`). Après une installation pip, ce répertoire n'existe pas forcément ;
le code le vérifie avec `is_dir()`.

!!! warning "`fork=True` sans `resume` est silencieusement sans effet"
    `fork_session` et `resume_session_at` sont tous deux imbriqués dans `if resume:` — sans `resume`, ils n'ont strictement aucun effet,
    **et aucune erreur n'est levée**. De même, `Runtime.run(resume_at=...)` n'agit que si `resume` est fourni,
    et **`Workflow` ne transmet jamais `resume_at`** : pour revenir en arrière à un message donné, il faut appeler `Runtime.run` directement.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Le tableau de bord de l'auto-[compact](glossary.md#压缩) ; il produit un jeu de variables d'environnement à injecter dans le sous-processus.
L'algorithme de compact lui-même est dans le binaire du harness et n'est pas modifiable ; seul le « déclencher ou non » l'est.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = rien n'est réglé, seuil = fenêtre − 33k ; `"no_summary"` → `DISABLE_AUTO_COMPACT=1` ; `"off"` → `DISABLE_COMPACT=1` (désactive aussi `/compact`). **Toute autre valeur lève `ValueError`**, elle n'est pas ignorée silencieusement |
| `window` | `int \| None` | `None` | Si non-`None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Le CLI limite à 100k–1M ; une valeur inférieure à 100k est remontée à 100k |

| Méthode | Signature | Description |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produit les variables d'environnement. **C'est ici qu'un `mode` invalide lève `ValueError`, pas à la construction** — comme elle est appelée par `build_options`, l'erreur apparaît dans `Runtime.run` |

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

L'objet de politique qui, quand le contexte est presque plein, préfère « écrire un [document de passation](glossary.md#交接书) et repartir sur une nouvelle session » plutôt que compacter.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Désactivé, on retombe sur l'auto-compact |
| `window` | `int` | `default_window()` | Taille supposée de la fenêtre de contexte du modèle |
| `headroom` | `int` | `50_000` | Marge à conserver. Raison : l'auto-compact se déclenche à fenêtre −33k, la passation doit arriver avant, et « écrire la passation » consomme encore un tour |
| `max_generations` | `int` | `8` | Nombre maximal de générations par step. **C'est une vanne anti-emballement, pas un dimensionnement de capacité** |

| Propriété | Type | Description |
|---|---|---|
| `at` | `@property -> int` | Seuil de passation `max(10_000, window - headroom)`. **Plancher à 10k** — en dessous, on n'arrive même plus à écrire la passation |
| `warn_at` | `@property -> int` | Position de l'alerte d'approche `max(1_000, at - 20_000)`, envoyée une seule fois par génération |

!!! warning "Un `window` sous-dimensionné provoque des passations infinies et brûle de l'argent"
    Si `at` tombe sous le **plancher de démarrage** du rôle (mesuré à environ 34k pour le coordinateur), chaque nouvelle session franchit la ligne dès sa première prise de parole ; et
    **une passation ne consomme pas de quota de retry** (`attempt -= 1`), d'où une boucle à vide infinie. La seule vanne est `max_generations=8` ;
    une fois atteinte, l'`error` est remplacée par un diagnostic invitant à augmenter `window` ou à désactiver les passations.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Devine la fenêtre de contexte à partir de la **chaîne du nom de modèle** dans les variables d'environnement `ANTHROPIC_MODEL` ou `ANTHROPIC_DEFAULT_OPUS_MODEL` :

| Condition | Retour |
|---|---|
| Le nom contient le mot isolé `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| Le nom contient `haiku` | `200_000` |
| Sinon (**y compris quand aucune des deux variables n'est définie**) | `1_000_000` |

**La valeur par défaut est optimiste.** Surestimer n'est pas une erreur fatale : l'API renvoie `prompt is too long`, `Runtime` reconnaît ce signal
(via son `is_overflow` interne) et passe immédiatement à la génération suivante — mais la passation de cette génération-là est une version dégradée.

---

## Documents {#文书}

Sources : [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Quatre dataclasses, toutes sur le principe « parser une réponse du modèle en un nombre fixe de sections, puis l'écrire sur disque ». Forme commune :
`parse()` pour parser, `missing()` / `complete()` pour vérifier la complétude, `to_markdown()` pour l'humain,
`prompt_block()` pour le modèle en aval, `write()` / `load()` pour écrire et relire.

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
`goal` → `accept` → `bounds` → `unknowns`, dont les noms de section en chinois sont respectivement «目标», «验收标准», «边界», «未知与假设».

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `goal` | `str` | `""` | Objectif |
| `accept` | `str` | `""` | Critères de recette |
| `bounds` | `str` | `""` | Limites |
| `unknowns` | `str` | `""` | Inconnues et hypothèses |
| `path` | `Path \| None` | `None` | Emplacement sur disque. `compare=False`, n'entre pas dans la comparaison d'égalité |

| Méthode | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Noms chinois** des sections manquantes, directement affichables |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parse les quatre sections depuis la réponse du modèle. **Retire d'abord les blocs de code clôturés**, laisse vide ce qui n'est pas trouvé |
| `to_markdown` | `() -> str` | Document complet avec en-tête de métadonnées, les sections vides deviennent `"(未填)"` |
| `prompt_block` | `() -> str` | Version compacte pour l'aval, **uniquement les sections non vides**, sans métadonnées |
| `write` | `(path: str \| Path) -> Path` | Crée le répertoire parent, écrit, affecte à `self.path` le chemin résolu et le retourne |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Retourne `None` si le fichier n'existe pas ou en cas d'`OSError`. **Reconvertit le placeholder `"(未填)"` en chaîne vide** |

Règles de parsing (là où se concentrent les pièges) :

- Lors du retrait des blocs clôturés, **une ``` ou un `~~~` non refermé fait jeter tout ce qui suit** — en pratique, le clarificateur colle parfois tout le code dans sa réponse.
  Quand la sortie du modèle est tronquée, plus aucune section suivante n'est parsée, donc `complete()` vaut `False` et le gate renvoie à la case départ.
- La regex de titre tolère `## 目标`, `**目标**`, `目标:`, `3. 边界`, ainsi que du corps de texte accolé directement au titre.
- La table d'alias est compilée par longueur décroissante, sinon « 未知 » avalerait « 未知与假设 » en premier.
- Quand une même section apparaît plusieurs fois, **on prend la première non vide**.
- Si, en éditant le brief à la main, vous recopiez le placeholder `"(未填)"` de `to_markdown()`, la section reste considérée comme manquante.

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

Le [document de passation](glossary.md#交接书) écrit lors d'un [changement de génération](glossary.md#换代), cinq sections.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `doing` | `str` | `""` | Ce qui est en cours. **Obligatoire** |
| `decided` | `str` | `""` | Ce qui a été décidé |
| `deadends` | `str` | `""` | Les impasses |
| `next` | `str` | `""` | Prochaine étape. **Obligatoire** |
| `scene` | `str` | `""` | État des lieux |
| `step` | `str` | `""` | Sert uniquement à l'en-tête du document, **n'entre pas dans le parsing** |
| `path` | `Path \| None` | `None` | Emplacement sur disque |

**Seules `doing` et `next` sont obligatoires** — exiger en dur une section « impasses » non vide pousserait le modèle à inventer.

| Membre | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Ne vérifie que les deux sections obligatoires** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Le corps porte-t-il la marque de dégradation `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Réutilise le découpeur de sections de `Brief` |
| `to_markdown` | `() -> str` | Les sections vides deviennent `"(空)"` |
| `prompt_block` | `() -> str` | **L'en-tête dit explicitement au repreneur « tu prends la suite »**, pour l'empêcher de repartir demander du contexte à quelqu'un |
| `write` | `(path) -> Path` | Comme `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Comme `Brief.load` |

Trois membres du même module, **non exportés mais sémantiquement décisifs** : `is_overflow(*texts)` reconnaît `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, etc., et transforme une « erreur dure » en « passation immédiate » ; `HANDOFF_PROMPT` est le prompt qui demande
**à la session courante elle-même** d'écrire la passation (avec les deux placeholders `{used}` et `{window}` ; **ce n'est pas un nouveau rôle** —
elle seule dispose de ce contexte) ; `degraded(step, prompt, *, why="")` assemble mécaniquement une passation quand celle-ci n'a pas pu être écrite,
en mettant dans `scene` les **1200** premiers caractères de la tâche d'origine.

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
| `unverifiable` | `@property -> list[str]` | Les items de `checks` marqués `[此环境无法验证:…]`. **Ils sont condamnés à ne jamais passer dès l'instant où l'objectif est fixé** |
| `missing` | `() -> list[str]` | Exige `statement` non vide **et** `checks` non vide |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | Un item de `checks` par ligne, les marqueurs `-` / `*` / `1.` sont retirés automatiquement |
| `to_markdown` | `() -> str` | Écrit `"(空)"` quand la liste est vide |
| `prompt_block` | `() -> str` | Version compacte pour l'aval |
| `write` / `load` | Comme `Brief` | Écriture et relecture |
| `amend` | `(extra: str) -> Goal` | **Ajoute sans écraser** : concatène `"\n\n(已修改)" + extra` après `statement` et retourne `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Le résultat d'un verdict de tour rendu par le [juge](glossary.md#判定者), **exactement trois sections** : conclusion / justification / non passés.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, `""` si non parsable |
| `reason` | `str` | `""` | Justification |
| `failed` | `list[str]` | `[]` | Les items de la liste qui n'ont pas passé |

| Membre | Signature | Description |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Une conclusion a-t-elle pu être extraite. **`ok=False` doit être traité comme « non atteint », jamais comme atteint** |
| `parse` | `@classmethod (text) -> Verdict` | Voir ci-dessous |
| `feedback` | `() -> str` | Le message renvoyé au worker : uniquement « ce qui manque », pas de solution |

Ordre de reconnaissance de `parse` :

1. Chercher d'abord la section titrée «结论» / «判定».
2. En l'absence de section titrée, sur le texte entier une fois `strip()` : `fullmatch(r"1|true")` → atteint ; `fullmatch(r"0|false")` → pas encore.
3. Sinon, chercher dans le texte de la conclusion le premier mot d'état trouvé dans la table (**les mots longs d'abord**).
   **«无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» sont tous rangés dans `unreachable`** —
   accident constaté : plateforme cible macOS, exécution dans un conteneur Linux, et le juge a validé après avoir simplement lu la branche dans le code source.
4. Toujours rien → chercher un `\b1\b` isolé → atteint, `\b0\b` → pas encore.
5. Aucun cas ne s'applique → `state=""`, `ok=False`.

`unreachable` et `not_yet` **sont deux conclusions différentes** : la première emprunte la voie « on s'arrête et on demande à un humain », pas « on refait un tour ».

## Couche hook {#hook}

Source : [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Cette couche est la **frontière d'exécution** de flower : quels outils le main thread n'a pas le droit de toucher, comment on rogne un résultat trop long, quel rôle part dans un worktree indépendant — tout est imposé par les hooks du SDK, **pas par le prompt**. La raison est directe : un prompt est une suggestion, le modèle peut l'ignorer ; on a mesuré que même avec un system prompt qui dit explicitement « n'utilise pas de worktree », l'injection d'`isolate_guard` s'applique quand même (le modèle passe `None`, ce qui atterrit est `'worktree'`).

Neuf exports : cinq fabriques de guard renvoyant un `HookMatcher` (`whitelist_guard` peut renvoyer `None`), un assembleur, un fusionneur, deux fonctions de marquage d'isolation.
Il n'y a pas besoin de les brancher à la main — [`Runtime`](#runtime) les monte automatiquement d'après l'`AgentSpec`. Le branchement manuel n'est nécessaire que si vous pilotez le SDK vous-même (sans passer par `Runtime`).

**La détection du main thread passe par une seule fonction** : `_is_main_thread(data) = not data.get("agent_id")` — les données de hook du cycle de vie d'un outil de subagent portent un `agent_id`, celles du [main thread](glossary.md#主线程) non.
Tous les guards « qui n'interceptent que le main thread » reposent sur cette ligne.

Constantes de groupes d'outils (au niveau module, non exportées, mais qui déterminent les matchers par défaut) :

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tableau de référence : quel guard sur quel événement SDK {#hook-速查表}

| Fonction | Événement hook SDK | matcher | Cible interceptée | Ce qui est renvoyé | Qui le monte |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | ceux de `Bash\|Write\|Edit\|NotebookEdit` qui **ne sont pas dans `allowed_tools`** | appel d'un outil interdit **par le main thread uniquement** | `permissionDecision: "deny"` + motif | `Runtime._attempt`, **uniquement si `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (modifiable via `tools=`) | **le main thread uniquement** qui met les mains dedans ; avec `allow_glance=True`, les `Bash` qui passent `is_ephemeral()` sont laissés passer | `deny` + « délègue à un subagent » | `workbench_hooks(delegate_only=True)`, **uniquement si `Runtime` a un workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sans `cwd` ni `isolation`, et `subagent_type` marqué par `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injecte `isolation="worktree"`) | `workbench_hooks`, **uniquement si `agents` contient un rôle marqué** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` situé dans `workbench.root` | `{}` (l'effet de bord est `workbench.refresh()`) | `workbench_hooks`, toujours monté |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | les **champs chaîne** de `tool_response` d'au moins `threshold` caractères ; la lecture du répertoire de spill lui-même passe | `updatedToolOutput` (spill + une ligne de pointeur + les 400 premiers caractères) | `workbench_hooks`, **uniquement si `spill_threshold` est vrai** |

**La conclusion clé qu'on lit dans ce tableau** : avec `Runtime(workbench=False)`, `workbench_hooks` n'est pas monté du tout ;
et pour un coordinateur en `delegate_only=True`, `whitelist_guard` est également sauté — **le main thread n'a plus aucun mur**.
Voir l'avertissement dans [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Rend `allowed_tools` réellement exclusif pour les quatre outils qui mettent les mains dedans.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obligatoire, positionnel | on passe généralement directement `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | la façon dont l'agent se désigne dans le texte de refus. `Runtime` passe `spec.name` |

- **Monté sur `PreToolUse`**, le matcher est `"|".join(banned)`, où `banned` = ceux parmi `Bash` `Write` `Edit` `NotebookEdit` qui ne sont pas dans `allowed`.
- En cas de correspondance : `permissionDecision: "deny"`, avec un texte du genre : « XX n'a pas YY. **C'est intentionnel, ce n'est pas une configuration oubliée.** Écris la conclusion dans le corps de ta réponse, le framework la lira là — n'essaie pas d'autres formulations pour contourner. »
- **N'intercepte que le main thread de la session**, les subagents passent — les outils d'un subagent sont déterminés par `AgentDefinition.tools`.
- Renvoie **`None`** quand il n'y a rien à intercepter (par exemple un rôle comme `worker()` qui a la panoplie complète) ; l'appelant décide sur cette base de le monter ou non.

**Pourquoi il doit exister** : `allowed_tools` est une **liste de dispense d'approbation, pas une liste blanche exclusive**. Deux preuves mesurées : un judge avec objectif a lancé 11 fois `Bash` ; dans une sonde à $0.1, un agent avec `allowed_tools=["Read"]` a quand même pu appeler `Write`/`Bash`.
Donc le « pas d'outil d'écriture » de `clarify()` / `judge()` **repose sur ce hook**, pas sur la liste blanche elle-même.

L'avantage est qu'il se dérive d'`allowed_tools` : `judge(can_run=True)` conserve donc automatiquement `Bash` tout en continuant à bloquer `Write`/`Edit` — sans interrupteur supplémentaire.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Le main thread met les mains dedans → refus, avec indication de la marche à suivre.**

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | le matcher. C'est une chaîne regex, pas une liste |
| `allow_glance` | `bool` | `False` | si `True`, laisse passer quand `tool_name == "Bash"` et [`is_ephemeral(command)`](#is-ephemeral) est vrai |

- **Monté sur `PreToolUse`**, le matcher est exactement `tools`.
- Le main thread appelle un de ces quatre outils → deny, et le motif **indique l'étape suivante** : utiliser l'outil `Agent` pour déléguer à un subagent, écrire dans la tâche l'objectif et les critères d'acceptation, et lui demander d'écrire les productions longues dans `.flower/artifacts/` en ne renvoyant que le chemin et la conclusion.
- Les subagents passent systématiquement.

La différence avec `whitelist_guard` est la **formulation** : les deux interceptent le même lot d'outils, mais celui-ci dit « délègue », ce qui est plus approprié.
C'est pourquoi un rôle en `delegate_only=True` ne monte que celui-ci ; les monter tous les deux enverrait au modèle deux directives contradictoires.

Le critère de passage d'`allow_glance=True` et la question « le résultat va-t-il être rogné » utilisent **la même fonction** ([`is_ephemeral`](#is-ephemeral)) — l'ensemble des commandes laissées passer doit être égal à l'ensemble des résultats qui périment ; modifier l'un oblige à modifier l'autre.

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

Les résultats d'outil dépassant le seuil sont **spillés sur disque immédiatement** ([spill](glossary.md#落盘)), il ne reste qu'une ligne de pointeur dans le contexte — au lieu d'attendre que le contexte soit plein pour compacter après coup.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, positionnel | le répertoire de spill est `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | nombre de caractères à dépasser pour déclencher le spill |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | le matcher |
| `main_only` | `bool` | `False` | `False` (défaut) = les résultats des subagents sont aussi spillés |

- **Monté sur `PostToolUse`**, renvoie
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <version rognée>}}`.
- Le nom du fichier de spill est les 16 premiers caractères du `sha256` du contenu + `.txt` ; dans le contexte, on met une ligne de pointeur + les **400 premiers caractères**.
- `updatedToolOutput` **doit conserver la structure de sortie de l'outil d'origine**, donc on ne remplace que les **champs chaîne** trop longs du dict ; **on ne touche jamais aux list** (elles peuvent contenir des blocs image). Une structure incorrecte est rejetée (le texte d'origine est conservé, sans erreur).
- **Il faut impérativement laisser passer la lecture du fichier de spill lui-même** — sinon « lis-le avec `Read` » est un vœu pieux : le texte relu est de nouveau spillé, boucle infinie.
  Rencontré en conditions réelles : le modèle a essayé cinq formulations pour contourner.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Dès qu'on écrit quelque chose dans le [workbench](glossary.md#工作台), rafraîchit `INDEX.md` ; l'agent suivant sait dès son ouverture que le fichier existe.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, positionnel | périmètre de détection et cible du rafraîchissement |

**Monté sur `PostToolUse`**, matcher `"Write|Edit"`. Si `tool_input["file_path"]` une fois résolu tombe dans `workbench.root`, appelle `workbench.refresh()`. **Renvoie toujours `{}`** — il ne modifie rien, il n'a que des effets de bord.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Attribue un git worktree indépendant aux subagents selon leur rôle, ce qui réalise l'[isolation](glossary.md#隔离).

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obligatoire, positionnel | table des rôles, sert à vérifier si `subagent_type` est marqué |
| `on_inject` | `Any` | `None` | callback optionnel, appelé sous la forme `on_inject(subagent_type, description)` |

**Monté sur `PreToolUse`**, matcher `"Agent"`. L'injection n'a lieu que si trois conditions sont réunies : `tool_name == "Agent"`, `tool_input` **n'a ni `cwd` ni `isolation`**, et le rôle correspondant à `subagent_type` est marqué par `isolated()`. Si c'est le cas, renvoie `permissionDecision: "allow"` + `updatedInput` (avec `isolation` mis à `"worktree"`).

`isolation` et `cwd` sont **mutuellement exclusifs** dans l'outil `Agent` — si le modèle a lui-même spécifié un `cwd`, on le respecte.
« Faut-il isoler » est un **attribut du rôle**, pas un interrupteur global, et ce n'est pas décidé à chaque délégation ; un rôle qui n'a pas besoin d'isolation ne reçoit pas un seul octet en plus.

**Activer l'isolation impose de sortir le [workbench](glossary.md#工作台) du dépôt.** Un agent isolé ne peut pas écrire dans le checkout partagé, donc le workbench doit pointer hors du dépôt via `home=`. `starter_flow(isolate=True)` utilise `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` utilise `<run_dir>/workbench` — les deux sont hors du dépôt, **mais ce ne sont pas le même répertoire**, ne les mélangez pas.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marque une définition de subagent comme « nécessite un espace de travail indépendant », et relit ce marquage.

| Fonction | Paramètre | Défaut | Description |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obligatoire | la définition à marquer. **Renvoie le même objet** |
| | `flag: bool` | `True` | positionnel. `False` = retire le marquage |
| `wants_isolation` | `agent: AgentDefinition \| None` | obligatoire | accepte `None`, renvoie alors `False` |

Le marquage est un attribut côté Python `_flower_isolate` posé via `object.__setattr__`, **ce n'est pas un champ de dataclass** — le SDK sérialise avec `asdict()` et ne reconnaît que les champs déclarés, donc ce marquage ne fuit pas jusqu'à la CLI (mesuré).

**Le coût** : faire un `dataclasses.replace()` sur une `AgentDefinition` perd ce marquage, et l'isolation devient silencieusement inopérante.

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

Monte en une fois les quelques hooks dont le workbench a besoin. C'est ce qu'appelle `Runtime._attempt`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `workbench` | `Workbench` | obligatoire, positionnel | passé à `index_guard` et `spill_guard` |
| `delegate_only` | `bool` | `True` | `delegate_guard` n'est monté que si `True` |
| `spill_threshold` | `int \| None` | `4000` | `spill_guard` n'est monté que si la valeur est vraie |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | `isolate_guard` n'est ajouté que si **au moins un** rôle est marqué par `isolated()` |
| `allow_glance` | `bool` | `False` | transmis à `delegate_guard(allow_glance=)` |

Résultat :

- `PreToolUse` : `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]` ;
  s'il y a un rôle marqué → ajoute `isolate_guard(agents)`.
- `PostToolUse` : toujours `[index_guard(workbench)]` ; si `spill_threshold` est vrai → ajoute
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Les clés d'événement dont la liste est vide sont supprimées**, on ne renvoie pas de list vide.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatène** plusieurs groupes de configuration de hooks par nom d'événement.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variadique | autant de groupes que voulu. Les groupes `None` sont ignorés |

Utilise `extend`, **sans déduplication** — passer le même guard deux fois le monte deux fois. `Runtime` s'en sert pour fusionner `spec.hooks`, `workbench_hooks(...)` et `whitelist_guard`.

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

Le répertoire de travail sur disque : trois sous-répertoires + un index. L'index est **injecté dans le system prompt**, l'agent sait donc à chaque tour ce qu'il a sous la main.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `workspace` | `Path` | obligatoire, positionnel | l'espace de travail. `__post_init__` le résout |
| `dirname` | `str` | `".flower"` | nom du répertoire du workbench, relatif à `workspace` |
| `max_index_entries` | `int` | `40` | **ne concerne que `prompt_block()`** : nombre maximal d'entrées listées par catégorie dans le bloc injecté au system prompt, le reste étant condensé en une ligne « … et N autres ». `INDEX.md` lui-même n'est pas limité, il liste tout |
| `home` | `Path \| None` | `None` | s'il est fourni, il sert de `root` et **`dirname` est ignoré**. Résolu aussi lorsqu'il n'est pas `None` |

| Membre | Signature | Description |
|---|---|---|
| `root` | `@property -> Path` | `home` s'il est fourni, sinon `workspace / dirname` |
| `external` | `@property -> bool` | si `root` est **en dehors** de `workspace`. Doit valoir `True` en mode isolation |
| `scripts` | `@property -> Path` | `root / "scripts"`, les scripts destinés à être relancés |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, les productions longues de plus de 2000 caractères |
| `notes` | `@property -> Path` | `root / "notes"`, les décisions clés, un fichier par décision |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | le chemin montré au modèle : relatif dans l'espace de travail, absolu à l'extérieur |
| `ensure` | `() -> Workbench` | `mkdir` des trois répertoires, renvoie `self` (chaînable : `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(chemin affiché, description, octets)`. `rglob("*")` récursif, ignore les fichiers commençant par `.` |
| `refresh` | `() -> str` | réécrit `INDEX.md` et renvoie son contenu |
| `prompt_block` | `() -> str` | **le bloc injecté dans le system prompt**. Volontairement court — il est là à chaque tour |

Format d'auto-description d'un script : `# desc: une phrase` dans les 8 premières lignes (les marqueurs `//` et `--` sont aussi reconnus),
à défaut le premier commentaire non vide ou la première ligne de la docstring (tronquée à 100 caractères).

Les trois règles injectées par `prompt_block()` :

1. Les scripts destinés à être relancés vont dans `scripts/`, avec `# desc:` en première ligne.
2. Les productions de plus de **2000 caractères** vont dans `artifacts/`, la conversation ne contient que le chemin et la conclusion.
3. Les décisions clés vont dans `notes/`, un fichier par décision.

Quand `external=True`, `prompt_block()` ajoute une phrase supplémentaire : « accède-y par chemin absolu ».

**L'index n'est pas hérité par les subagents.** Il passe par le `system_prompt.append` au niveau de la session, or un subagent a son propre system prompt (mesuré à $0.2461). Donc « écrire les productions longues dans `artifacts/` » et « où se trouve le workbench » doivent être relayés par le [coordinateur](glossary.md#协调者) dans le [task brief](glossary.md#任务书) — **c'est le seul canal**, ce n'est pas une redondance.
Ce point est **délibérément absent** de `WORKER_RULES` : le chemin réel est produit par `Workbench`, l'écrire en dur serait faux.

---

## Session store {#会话存储}

Sources : [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Trois niveaux d'héritage : `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **utilise toujours le niveau le plus externe**, les politiques des trois niveaux sont contrôlées par les paramètres du constructeur.

Chaque niveau gère une chose : la persistance, le [trim](glossary.md#裁剪) par taille et par valeur, le [prune](glossary.md#剪除) selon « est-ce une erreur ».
Le trim et le prune ont tous deux lieu au moment du **`load()`** (c'est-à-dire quand le resume réinjecte l'historique dans le modèle), les enregistrements bruts dans SQLite ne bougent pas d'un octet.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implémente le protocole `SessionStore` du SDK, trois tables `entries` / `meta` / `summaries`.
La clé du store est `project_key/session_id[/subpath]` — **les transcripts des sous-agents se distinguent par le subpath**.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `path` | `str \| Path` | obligatoire, positionnel | le fichier de base de données. La connexion utilise `check_same_thread=False` |

| Méthode | Signature | Description |
|---|---|---|
| `append` | `async (key, entries) -> None` | déduplication idempotente par uuid (d'abord ce qui est déjà en base, puis les doublons du lot). Lors d'un rejeu complet du lot, **ne fait pas avancer le mtime et ne replie pas le summary** ; seul le transcript principal (`subpath is None`) participe au summary |
| `projects` | `() -> list[str]` | les `project_key` réellement présents en base. **Le SDK les déduit du cwd ; confirmez avec ceci avant de requêter, ne devinez pas** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **synchrone, ne lit pas le payload**, une seule ligne de meta. Sert à la [continuité](glossary.md#接续) sur le même chemin — reprendre une session inexistante n'explose qu'une fois le sous-processus démarré |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | quelle taille de contexte le modèle a réellement vue au dernier tour, `0` si introuvable. Ne parcourt à rebours que les `scan` dernières entrées ; compte les trois postes `input + cache_read + cache_creation` (ne regarder qu'`input_tokens` sous-estime gravement) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | trié par seq ; renvoie `None` s'il n'y a aucune ligne |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | seulement les transcripts principaux |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | liste les résumés de sessions |
| `delete` | `async (key) -> None` | supprimer un transcript principal **supprime en cascade ceux des sous-agents**, pour éviter les orphelins |
| `list_subkeys` | `async (key) -> list[str]` | liste les sous-transcripts de cette session |
| `close` | `() -> None` | ferme la connexion |

Le `_next_mtime` interne garantit une **stricte monotonie** — `list_sessions` et le sidecar de summary partagent cette horloge, sinon le chemin rapide de détection de péremption du SDK se trompe.

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
| `keep_recent` | `int` | `20` | les N derniers `tool_result` gardent leur texte d'origine |
| `min_chars` | `int` | `2000` | les résultats courts ne valent pas la peine d'être rognés |
| `spill_dirname` | `str` | `".flower/spill"` | **relatif à `workspace`, doit être dans l'espace de travail** — sinon le `Read` de l'agent n'y accède pas |
| `enabled` | `bool` | `True` | vaut `False` avec `Runtime(trim=False)` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | produit la ligne de pointeur qui remplace le corps |

**Les deux répertoires de spill ne sont pas le même.** `spill_guard` écrit dans `<workbench.root>/spill/` (qui peut être hors de l'espace de travail) ;
`TrimPolicy.spill_dirname` écrit dans `<workspace>/.flower/spill/` (**qui doit être dans l'espace de travail**).
Ils correspondent respectivement au « rognage à chaud » et au « rognage au resume » ; la différence de répertoire est intentionnelle, ne les fusionnez pas.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Politique de péremption des résultats des [commandes éphémères](glossary.md#一次性命令).

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | désactivé, le marquage de péremption n'a pas lieu du tout |
| `keep_recent` | `int` | `6` | les N derniers sont exemptés. **Bien plus petit que le 20 de `TrimPolicy`** |
| `max_chars` | `int` | `2000` | au-delà, on saute et on laisse `TrimPolicy` archiver |
| `text` | `str` | voir la signature | texte de remplacement, deux emplacements `{cmd}` et `{age}` |

| Méthode | Signature | Description |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | applique `text` pour produire le corps de remplacement |

**Ne s'applique qu'aux résultats de l'outil `Bash`**, et la commande doit correspondre à la liste blanche des commandes éphémères. **`Read` n'en fait pas partie** — le contenu d'un fichier ne se déforme pas assez avec le temps pour induire en erreur. Le contenu périmé **n'est pas spillé**, il est jeté.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Détermine si une commande Bash est une [commande éphémère](glossary.md#一次性命令).
**Le critère de passage de `delegate_guard` et le critère de péremption du trim partagent cette unique fonction** — l'ensemble des commandes que le coordinateur peut exécuter lui-même doit être égal à l'ensemble des résultats marqués périmés. Laisser passer sans rogner, et un `git status` périmé occupe le contexte pour toujours en plus d'induire en erreur ; rogner sans laisser passer, et le coordinateur délègue un subagent pour un `ls`, soit 4,3k de coût de démarrage pour quelques dizaines de caractères.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `cmd` | `str` | obligatoire, positionnel | la ligne de commande complète |

Ordre d'évaluation :

1. Vide / uniquement des blancs → `False`.
2. Substitution de commande (`$(`, backticks, `<(`, `>(`) ou une écriture « qui modifie l'état » → `False`.
3. Après avoir retiré les redirections sûres (`2>&1`, `&> /dev/null`, etc.), s'il reste `>` ou `<` → `False`.
4. Après avoir retiré `&&` / `||` / `;` / `|`, s'il reste un `&` isolé (exécution en arrière-plan) → `False`.
5. Découpe sur `&&` / `||` / `;` / `|`, **chaque segment doit correspondre à la liste blanche**.

Grandes catégories de verbes de la liste blanche : les sous-commandes `git` en lecture seule (`status` `diff` `log` `show` `branch` `rev-parse`, etc.), les informations de répertoire et de système (`ls` `pwd` `df` `du` `date` `whoami` `env`, etc.), les processus et conteneurs (`ps` `top` `lsof` `docker ps` `kubectl get`, etc.), la consultation de fichiers (`cat` `head` `tail` `wc` `stat` `find` `tree`), la recherche de chemins (`which` `whereis` `command -v` `type`), le traitement de texte (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff`, etc.).

Même avec un verbe en liste blanche, ces écritures sont bloquées : `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` et `print >` dans `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

La première version refusait en bloc toutes les commandes composées, ce qui **rendait le glance totalement inopérant** en pratique (les trois tentatives du coordinateur ont été bloquées) ; d'où le passage à une évaluation segment par segment.

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
| `path` | `str \| Path` | obligatoire | le fichier de base de données |
| `workspace` | `str \| Path` | obligatoire | la base de référence du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | si absent, `TrimPolicy()` par défaut |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | si absent, `EphemeralPolicy()` par défaut |

Attributs publics : `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Ordre dans `load()` : `super().load()` → vide `last_report` → si `ephemeral.enabled`, `expire()` →
si `policy.enabled`, `trim()`. **Avec `enabled=False`, l'étape est entièrement sautée.**

| Méthode | Description |
|---|---|
| `expire(entries)` | remplace **seulement le corps** des résultats `Bash` périssables périmés, **le bloc est conservé**. La commande est retrouvée dans le `tool_use` du message assistant précédent ; ignore `isCompactSummary` / `isMeta` ; saute ce qui dépasse `max_chars` (laissé à `trim`) ; les `keep_recent` derniers sont exemptés. Écrit `last_report["expired"]` |
| `trim(entries)` | le corps des `tool_result` `>= min_chars` est spillé dans `<workspace>/<spill_dirname>/<16 premiers caractères du sha256>.txt`, le contenu du bloc est remplacé par un pointeur ; les `keep_recent` derniers sont exemptés. Écrit `cleared` / `kept` / `chars_saved` dans `last_report` |

**Ne rogne que du texte brut** : les blocs `image` / `document` sont laissés tels quels.

**Deux lignes rouges structurelles** : le **bloc `tool_result` doit rester présent**, on ne peut remplacer que le content (un bloc manquant = « Missing Tool Result Block ») ; les entrées `isCompactSummary` ne doivent pas être touchées.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Rend `store.last_report` sous forme d'une ligne, pour les logs de l'UI.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obligatoire, positionnel | accepte aussi la sous-classe `PruningSessionStore` |

Trois sorties possibles : rien fait → `"未裁剪"` ; uniquement des péremptions → `"N 个时效性结果标记为过期"` ;
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
| `drop_api_errors` | `bool` | `True` | retire les messages d'erreur API synthétiques (résidus de déconnexion) |
| `neutralize_interrupts` | `bool` | `True` | remplace les `tool_result` résiduels d'une interruption par une note neutre |
| `interrupt_text` | `str` | voir la signature | le texte de la note neutre |
| `keep_denials` | `int` | `1` | conserve les N derniers appels d'outil refusés |

La raison de `keep_denials` : un appel refusé n'a jamais été exécuté, son résultat ne contient aucune information, mais il occupe une place non négligeable (mesuré une fois à 273 caractères = 93 caractères de texte de refus + 180 caractères de **commande morte reproduite**). Plus grave encore, **il induit en erreur** : on a constaté qu'après avoir lu quelques « n'utilise pas directement Bash », le coordinateur n'essayait même plus les `git status` pourtant autorisés — de l'impuissance apprise.
**Par défaut on en garde 1 et non 0** : le refus le plus récent empêche le modèle de réessayer en boucle la même commande bloquée dans le même tour.

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
| `path` | `str \| Path` | obligatoire | le fichier de base de données |
| `workspace` | `str \| Path` | obligatoire | la base de référence du répertoire de spill |
| `policy` | `TrimPolicy \| None` | `None` | politique de trim |
| `prune` | `PrunePolicy \| None` | `None` | politique de prune |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | politique de péremption |

Trois attributs publics en plus de ceux de la classe parente : `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (donc `expire` + `trim` d'abord) → `self.prune(entries)`. `prune` fait trois choses :

1. **Retire les appels refusés trop anciens** : la détection repose sur le marqueur structurel du harness `toolDenialKind == "permission-rule"` (plus fiable que de faire correspondre le texte du refus) ; conserve les `keep_denials` derniers, et retire pour les autres le bloc `tool_use` **et** le bloc `tool_result`. Quand un même message assistant contient plusieurs `tool_use`, **seul celui visé est retiré**, sinon on obtient un « Missing Tool Result Block » ; les blocs texte et thinking sont conservés.
2. **Retire les messages d'erreur API synthétiques.** Ils restent tels quels dans SQLite, ils ne sont simplement pas réinjectés.
3. **Remplace les `tool_result` résiduels d'une interruption par une note neutre** — seul le corps est remplacé, l'entrée n'est pas retirée.

**L'unique ligne rouge structurelle** : le transcript est une chaîne simple par `parentUuid` ; retirer une entrée oblige à raccrocher ses enfants au plus proche ancêtre survivant.
Le `entries` du `relink` interne **doit être la liste complète (y compris les entrées à retirer)**, le filtrage est fait par lui-même — si l'appelant retire d'abord puis passe la liste, la chaîne se rompt là et tout l'historique antérieur est perdu (**déjà rencontré : invisible quand les entrées retirées sont en fin de liste, explosif quand elles sont au milieu**).

**L'ordre des paramètres diffère de celui de la classe parente** : la parente est `(path, workspace, policy, ephemeral)`, la fille est `(path, workspace, policy, prune, ephemeral)` — **le quatrième paramètre positionnel passe d'`ephemeral` à `prune`**, un passage positionnel décale silencieusement. Utilisez systématiquement des mots-clés.

---

## Résilience {#韧性}

Source : [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

En cas de coupure réseau, on reste suspendu à attendre plutôt que de sortir en échec. Quatre exports : une dataclass de politique + trois fonctions de sonde utilisables séparément.

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
| `max_attempts` | `int` | `6` | **première tentative incluse** |
| `base_delay` | `float` | `4.0` | base du backoff, en secondes |
| `max_delay` | `float` | `120.0` | plafond du backoff, en secondes |
| `probe_timeout` | `float` | `5.0` | timeout d'une sonde |
| `probe_interval` | `float` | `15.0` | attente entre deux sondes |
| `max_offline_wait` | `float` | `3600.0` | durée maximale d'attente suspendue, 1 heure par défaut |
| `retry_unknown` | `bool` | `True` | faut-il réessayer les erreurs non classables |
| `resume_prompt` | `str` | voir la signature | ce qu'on dit à la reprise. **Volontairement sans aucun détail d'erreur** — le modèle a besoin de savoir « tu as été interrompu, continue », pas de savoir si c'était un `ENOTFOUND` ou un 503 |

| Méthode | Signature | Description |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplié par `0.75 + random()*0.5` (gigue de ±25 %) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, ou `kind == "unknown"` avec `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | reste suspendu en attendant le retour du réseau. Renvoie `True` s'il revient, `False` au-delà de `max_offline_wait`. `notify` est un callback `(str) -> None`, appelé une fois **à la première injoignabilité** et une fois **au rétablissement** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Classe un texte d'erreur en trois catégories : `"transient"` / `"fatal"` / `"unknown"`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `text` | `str \| None` | obligatoire, positionnel | le message d'erreur d'origine. Renvoie `"unknown"` s'il est vide |

**On teste fatal avant transient** — les textes du type 401 contiennent souvent le mot `connection`, et dans l'ordre inverse on attendrait indéfiniment.

| Catégorie | Ce qui correspond |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

L'hôte et le port à sonder, dérivés d'`ANTHROPIC_BASE_URL`, par défaut `https://api.anthropic.com` ;
le port vaut par défaut `80` (http) ou `443`.

**Avec une passerelle auto-hébergée, il faut sonder celle-ci** — le fait qu'`api.anthropic.com` réponde ne dit rien sur la passerelle.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `host` | `str` | obligatoire, positionnel | nom d'hôte |
| `port` | `int` | obligatoire, positionnel | port |
| `timeout` | `float` | `5.0` | en secondes |

**Fait uniquement le DNS (`getaddrinfo`) + la poignée de main TCP**, n'envoie pas de HTTP, ne porte pas d'identifiants, **ne coûte rien**. Toute exception vaut injoignable.

---

## Événements et interaction {#事件与交互}

Code source : [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Un [événement](glossary.md#事件) est la structure stable dans laquelle le flux de messages du SDK est aplati.
**La [couche d'interaction](glossary.md#交互层) ne connaît que `Event` et n'importe aucun type du SDK** — c'est la frontière qui permet de changer d'UI sans toucher au cœur. Voir [Changer de couche d'interaction](../guide/interaction.md).

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
| `kind` | `EventKind` | requis | Voir le tableau ci-dessous |
| `text` | `str` | `""` | Corps du texte |
| `tool` | `str` | `""` | Nom de l'outil, uniquement pour `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | Informations structurées additionnelles |
| `raw` | `Any` | `None` | Objet SDK d'origine, pour creuser plus loin |

`__str__` : pour `tool_call`, c'est `f"[{tool}] {text}"`, sinon `text`, et si `text` est vide, `f"<{kind}>"`.
Donc `print(ev)` est directement lisible.

`EventKind` compte **15** valeurs :

| kind | Émis par | Description |
|---|---|---|
| `text` | `normalize` | Corps du message assistant |
| `thinking` | `normalize` | Bloc de réflexion |
| `tool_call` | `normalize` | Appel d'outil. `text` est un résumé de `file_path` / `command` / `pattern`, tronqué à 200 caractères |
| `tool_result` | `normalize` | Résultat d'outil. `text` tronqué à 500 caractères, `payload` porte `tool_use_id` / `is_error` |
| `task` | `normalize` | Les trois messages Task, `text` est le nom de classe du message |
| `system` | `normalize` | Les autres messages système, `text` est le subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` porte `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | Message d'erreur d'API synthétique, `payload` porte `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Le corps est une entrée, pas une production du modèle**, donc il n'entre pas dans `StepResult.text` |
| `unknown` | `normalize` | Non reconnu |
| `retry` | `Runtime` | Notification de retry |
| `step` | `Workflow.run` | payload : `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | dans payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | Question, **porte aussi « ce que l'humain dit spontanément »** |

**Les quatre derniers ne sont pas produits par `normalize()`.**

Le `payload` de tous les événements assistant / user porte :

| Clé | Type | Description |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | Présent uniquement si `subagent` est vrai |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **C'est l'unique source du critère de [handoff](glossary.md#换代)**, et le chiffre qu'un run de longue portée mérite le plus de voir |

**Le kind `ask` porte à la fois « une question » et « ce que l'humain dit spontanément ».** Dans le second cas,
`payload["kind"] == "mail"`, et **il n'y a ni `options` ni `remaining`**. L'UI doit d'abord tester
`payload.get("kind")` avant de décider comment rendre l'événement, sinon elle laissera une simple phrase
suspendue comme une question en attente de réponse.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Aplatit un message du SDK en 0 à N `Event`.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `message` | `Any` | requis, argument positionnel | N'importe quel objet message du SDK |

Branches clés :

- **Message d'erreur d'API synthétique** (`isApiErrorMessage=True` ou `model == "<synthetic>"`) → un unique
  `Event("error", payload={"synthetic": True})`. **C'est intentionnel** — sinon le texte de déconnexion serait pris
  pour du corps de message, entrerait dans `StepResult.text`, et serait transmis à l'étape suivante.
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
| `id` | `str` | requis | Sert à localiser la question au moment de répondre |
| `question` | `str` | requis | Corps de la question |
| `options` | `list[str]` | `[]` | Choix proposés. L'humain peut aussi ne rien choisir et taper sa propre réponse |
| `asked_at` | `float` | `time.time()` | Instant de la question |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | Corps de la réponse |

| Membre | Signature | Description |
|---|---|---|
| `waited_s` | `@property -> float` | Depuis combien de temps on attend |
| `event` | `(remaining: int = 0) -> Event` | Produit `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

Un **serveur MCP in-process** (deux outils) plus un jeu de méthodes destinées à l'UI. Côté modèle, on ne voit que
`mcp__human__ask` et `mcp__human__inbox`. Tous les paramètres du constructeur sont keyword-only.

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | La sortie du mode **push**. S'il est fourni, `Workflow.run` ne recâble plus rien |
| `max_asks` | `int \| None` | `None` | **Pas de limite**. Un nombre = quota dur, `0` = questions interdites (tout-automatique / CI). En cas de dépassement, l'outil **refuse directement, sans bloquer** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutes. `None` = attendre indéfiniment ; **`<= 0` = ne pas attendre, toute question tombe immédiatement dans le vide** |
| `log_path` | `str \| Path \| None` | `None` | Les questions/réponses sont **ajoutées** sur disque, sans occuper le contexte |
| `amend_path` | `str \| Path \| None` | `None` | Ce que l'humain dit en cours de run est ajouté à ce fichier (en général le brief lui-même). **Sans écriture sur disque, ça ne survit pas à la frontière d'étape** — l'étape suivante est une nouvelle session qui ne lit que les artefacts gelés |
| `over_budget_text` | `str` | constante du module | Ce qui est renvoyé au modèle en cas de dépassement de quota |
| `timeout_text` | `str` | constante du module | Ce qui est renvoyé au modèle en cas de timeout |
| `declined_text` | `str` | constante du module | Ce qui est renvoyé au modèle quand la question est passée |

Attributs publics : les huit homonymes des paramètres du constructeur, plus `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**les exceptions levées par les callbacks d'UI sont collectées ici, sans interrompre le run**).

| Membre | Signature | Description |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | À passer directement à `AgentSpec.mcp_servers`. **Le nom de clé doit coïncider avec le nom du serveur**, d'où le fait qu'il soit fourni d'un bloc |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | Suspend et attend l'humain. **Ne lève jamais d'exception hors `CancelledError`** — l'absence de réponse est aussi une réponse, à distinguer via `ask.state` |
| `send` | `(text: str) -> Mail \| None` | L'humain dit spontanément quelque chose. **Appelable depuis n'importe quel thread.** N'interrompt pas l'agent ; appelle `amend()` automatiquement en interne |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | Ajoute dans `amend_path`. Renvoie si l'écriture a réellement eu lieu (chemin non configuré, texte vide, `OSError` → `False`) |
| `pending_mail` | `() -> list[Mail]` | Les mails non encore récupérés |
| `remaining` | `@property -> int` | Combien de questions restent. **Renvoie `-1` quand `max_asks=None`**, ni 0 ni l'infini |
| `pending` | `() -> list[Ask]` | Les questions actuellement en attente de réponse |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | Pour le mode **pull**. Renvoie `None` en cas de timeout, lève si annulé |
| `answer` | `(ask_id: str, text: str) -> bool` | Répondre. `False` = cette question n'est plus en attente (timeout / déjà répondue) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | Passer, et laisser le modèle juger par lui-même |
| `transcript` | `() -> str` | Le markdown du journal des questions/réponses |

**Choisissez l'un des deux modes de récupération** : **push** — construire `HumanChannel(on_event=...)` ;
**pull** — `await channel.next_ask()`. `Workflow.run` ne câble automatiquement que si `channel.on_event is None`,
donc si vous l'avez fourni vous-même, il ne sera pas écrasé.

**Multi-thread** : `answer` / `decline` / `send` passent en interne par `loop.call_soon_threadsafe` ;
les appeler directement depuis un backend web ou un thread d'entrée TUI est la norme.

Les trois sémantiques « 0 / None » sont toutes différentes, ne les confondez pas : `max_asks=None` = illimité,
`max_asks=0` = questions interdites ; `timeout_s=None` = attendre indéfiniment, `timeout_s<=0` = timeout immédiat ;
`remaining` vaut `-1` quand `max_asks=None`.

`Mail`, non exporté mais présent dans les valeurs de retour, est une dataclass aux champs `id` / `text` / `sent_at` / `taken`.

---

## Lignage {#血缘}

Code source : [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Enregistre inter-processus « quelle étape a utilisé quelle session » ; c'est là-dessus que la
[continuité](glossary.md#接续) s'appuie pour retrouver où le run précédent s'était arrêté.
Le fichier est `<run_dir>/lineage.json`.

| Champ | Type | Défaut | Description |
|---|---|---|---|
| `path` | `Path` | requis | Chemin du fichier de lignage |
| `workspace` | `Path` | requis | Espace de travail. `__post_init__` le résout |
| `steps` | `dict[str, str]` | `{}` | Nom d'étape → `session_id` |
| `woke` | `int` | `0` | Nombre de réveils |

| Membre | Signature | Description |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | Lit `<run_dir>/lineage.json`. **Fichier absent, illisible, ou champ `workspace` qui ne correspond pas : renvoie systématiquement un lignage vide, sans erreur** |
| `remember` | `(step: str, session_id: str) -> None` | Mémorise l'association et **écrit immédiatement sur disque**. Retour direct si l'étape ou le sid est vide |
| `bump` | `() -> int` | Incrémente le compteur de réveils, écrit sur disque, renvoie la nouvelle valeur (`1` au premier run) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **Déplace** le fichier de lignage + `extra` vers `<into>/<YYYYmmdd-HHMMSS>/`, et remet `steps` / `woke` à zéro. **Déplacer n'est pas supprimer** |

L'écriture passe par un remplacement atomique `tmp.replace(path)` ; les `OSError` sont avalées silencieusement —
un échec d'écriture ne doit pas emporter le run.

**`workspace` est un garde-fou** : la `project_key` du SDK est dérivée du chemin de l'espace de travail ; si le
répertoire a été copié ailleurs, les anciens `session_id` sont introuvables, donc un chemin qui ne correspond pas
équivaut à rien.

Quand `Workflow.run` charge le lignage, il vérifie chaque entrée une par une avec `runtime.has_session(sid)` pour
s'assurer qu'elle est encore en base, et ne l'utilise que si elle est vivante — un fichier de lignage peut survivre
à `sessions.db`.

---

## Exemples minimaux utilisables {#示例}

Les cinq extraits tournent tels quels. Prérequis : `claude-agent-sdk` installé, `ANTHROPIC_API_KEY` ou
`ANTHROPIC_AUTH_TOKEN` disponible (sinon `Runtime(...)` lève `RuntimeError` dès la construction).

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

Les paramètres de `Runtime` sont **tous keyword-only** ; `spec` et `prompt` de `rt.run()` sont positionnels, le reste
est keyword-only. `AgentSpec` a pour défauts `allowed_tools=["Read", "Glob", "Grep"]` et `delegate_only=False`,
donc `Runtime` lui installe automatiquement [`whitelist_guard`](#whitelist-guard), qui bloque `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordinateur + exécutant {#示例-协调}

Un [coordinateur](glossary.md#协调者) qui ne met pas la main à la pâte, avec un [exécutant](glossary.md#执行者) qui
travaille. C'est la première couche d'économie de contexte de flower.

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
    # sans workbench, les Bash/Write du coordinateur n'ont aucun hook pour les intercepter.
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

Les deux premiers paramètres de `worker()` sont positionnels : `description` (ce qui sert au coordinateur pour
choisir) et `prompt` (son system prompt, auquel `WORKER_RULES` est concaténé automatiquement). Les trois premiers de
`coordinator()` sont positionnels : `name`, `instructions`, `workers`.

### Écrire son propre Workflow {#示例-workflow}

Deux étapes, la seconde injectant le résultat de la première dans son propre prompt — pas cher, isolé, sans session
partagée.

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
        # Pour continuer dans la même session, écrire resume_from="造句" ; pour bifurcer, ajouter fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (quand reduce n'est pas fourni)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # à quelle étape ça a échoué, quand on_fail="stop"


asyncio.run(main())
```

Les trois premiers champs de `Step` (`name` / `spec` / `prompt`) sont positionnels, tout comme `steps` de `Workflow`.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positionnel, les deux callbacks keyword-only.
**Attention, `continuous=True` est la valeur par défaut** : au deuxième run avec le même `run_dir` et le même
`workspace`, même les étapes à `resume_from=None` reprennent la session de la fois précédente.

### Ajouter un garde-objectif {#示例-目标}

D'abord laisser le [juge](glossary.md#判定者) fixer l'objectif et la liste de vérification, puis faire accepter le
verdict par l'étape de travail — si le verdict est négatif, on recommence avec le retour, trois tours au maximum.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = tout-automatique : toute question tombe immédiatement dans le vide, sans faire semblant d'attendre
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds est le **nombre total de tours** : rounds=3 → retries=2 → trois tours de travail au maximum
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # Le prompt de goal_step lit ctx["确认需求"] (valeur par défaut de brief_key).
        # Sans clarify_step, il faut en fournir un soi-même, sinon il ne verra que "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY : objet Goal
    print(ctx["_verdict"])     # VERDICT_KEY : dernier Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY : nombre de tours effectués
    print(ctx.get("_aborted")) # raison du StepAbort (objectif inatteignable et personne ne répond)


asyncio.run(main())
```

`with_goal` ne remplace que `gate` / `on_reject` / `retries` ; les autres champs sont repris tels quels via
`dataclasses.replace`. Le juge est une **session indépendante** : `gate` appelle en interne
`rt.run(judger, ..., step_name=f"{label}#{轮次}")`, avec `resume` toujours à `None`.

### Remplacer la couche d'interaction {#示例-交互层}

Pour passer du terminal au web / TUI / HTTP, il n'y a que deux choses à changer : la fonction qui rend l'`Event`, et
la coroutine qui récupère les questions.

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
    # Les kind == "ask" qui ne sont pas des mails sont traités par answerer ci-dessous (mode pull)


async def answerer(ch: HumanChannel) -> None:
    """Récupération des questions en mode pull. En passant à un backend web / service HTTP,
    cette coroutine est le seul endroit à modifier."""
    while True:
        ask = await ch.next_ask()          # sans timeout, attend indéfiniment
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # ou ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Le Runtime réutilise le workbench déjà créé par le workflow — n'en fabriquez pas un second
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push et pull : **choisissez-en un**. Push = construire `HumanChannel(on_event=...)`, pull = `await channel.next_ask()`.
`Workflow.run` ne câble automatiquement que si `channel.on_event is None`, donc si vous avez fourni `on_event`
vous-même, il ne sera pas écrasé. `answer()` / `decline()` / `send()` / `interrupt()` **sont tous appelables depuis
un autre thread**.

---

## Pièges et erreurs fréquentes {#陷阱}

Classés dans l'ordre où on les rencontre, pas par module. Chaque point vient d'une observation réelle.

### Assemblage {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = aucune barrière sur le thread principal.**
   `delegate_guard` n'est installé qu'en présence d'un workbench, et `whitelist_guard` est court-circuité par
   `delegate_only=True`. Si vous utilisez un coordinateur, activez le workbench. Voir [Runtime](#runtime).
2. **Il y a deux emplacements de workbench, ne les confondez pas.** `Runtime(workbench=True)` tombe dans
   `<run_dir>/workbench` ; `Workbench(ws)` vaut par défaut `<ws>/.flower`. Si vous construisez `brief_path` à la main
   selon le second, **le brief est écrit dans le répertoire A tandis que l'index injecté scanne le répertoire B —
   et rien ne remonte d'erreur**. La bonne pratique : que le workflow fasse lui-même `Workbench(...).ensure()`,
   l'accroche à `Workflow.workbench`, puis donne **le même objet** à `Runtime(workbench=wb)`.
3. **`allowed_tools` n'est pas une liste blanche exclusive, c'est une liste de dispense d'approbation.** Le modèle
   peut toujours appeler des outils qui n'y figurent pas. Le « pas d'outil d'écriture » de `clarify()` / `judge()`
   repose sur le hook [`whitelist_guard`](#whitelist-guard). Et `coordinator()` a pour défaut
   `permission_mode="acceptEdits"` — si quelqu'un passe cette valeur à `clarify()` / `judge()`, la protection
   disparaît.
4. **`disallowed_tools` est au niveau de la session** : il interdit aussi les outils homonymes chez les subagents.
5. **L'index du workbench n'entre pas dans les subagents.** « Les productions longues vont dans `artifacts/` » doit
   être retransmis par le coordinateur dans le brief de tâche : c'est le seul canal.
6. **`Runtime(...)` lève `RuntimeError` dès la construction en l'absence de credentials**, pas au moment de `run()`.
7. **`Runtime.run_id` doit être unique par instance.** `manifest.json` déduplique sur le champ `run` ; quand deux id
   entrent en collision, le dernier écrivain supprime les lignes de l'autre en les prenant pour « ce qu'il avait
   écrit la fois précédente ».

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` est la valeur par défaut** : `resume_from=None` ne signifie pas « session
   entièrement neuve ». Pour repartir de zéro à chaque fois, mettez explicitement `continuous=False`.
   **Renommer une étape revient à couper le lignage.**
9. **`with_goal(rounds=N)` est le nombre total de tours, pas le nombre de tours supplémentaires** :
   `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` n'écrit pas `ctx[step.name]`** — un `lambda ctx: ctx["某步"]` en aval lèvera un `KeyError`.
    Pour continuer avec un résultat incomplet, utilisez `on_fail="continue"`.
11. **Un `resume_from` pointant vers une étape non exécutée ou en échec lève un `ValueError`**, il n'est pas ignoré
    silencieusement.
12. **`Step.reduce` doit être une fonction synchrone ; `gate` / `when` / `on_reject` peuvent être async.**
13. **`fork=True` est silencieusement sans effet si `resume` n'est pas fourni.** `Workflow` ne transmet jamais
    `resume_at` ; pour revenir en arrière message par message, il faut appeler `Runtime.run` directement.
14. **Quand vous pilotez `Runtime` vous-même, `on_session` doit être détaché avant le gate**, sinon la session du
    juge sera inscrite dans le lignage de l'étape de travail. `Workflow` le garantit avec un `try/finally`.
15. **`step_name` détermine les clés dans le manifeste et dans le lignage.** `Workflow` ajoute les suffixes
    `#retryN` / `#roundN`, le juge ajoute `#轮次` — **les noms suffixés n'entrent pas dans le lignage
    inter-processus**, ce qui est précisément l'un des moyens d'assurer que « le juge est toujours une nouvelle
    session ».

### Rôles {#陷阱-角色}

16. **`clarify(max_turns=<petit nombre>)` vide de sens la promesse « questions illimitées »** — chaque question
    consomme un tour.
17. **`goal_step()` n'a pas de paramètre formel `can_run`** : il faut passer `can_run=True` via `**spec_kw`.
    Sans cela, le juge qui fixe l'objectif n'a pas `Bash`, et la règle de `JUDGE_RULES` « commence par bien voir
    dans quel environnement tu es » ne peut pas être exécutée.
18. **`judge(can_run=True)` permet au juge de modifier l'espace de travail** — `whitelist_guard` est dérivé de
    `allowed_tools` : donner `Bash` laisse passer `Bash` (`Write`/`Edit` restent bloqués, mais `Bash` peut lui-même
    écrire des fichiers). Pour une neutralité absolue, ne l'activez pas.
19. **`worker(isolate=True)` exige que l'espace de travail soit un dépôt git**, sinon l'outil `Agent` remonte
    directement `"not in a git repository"` ; il n'y a pas de dégradation silencieuse. De plus, le marqueur
    d'isolation est un attribut Python : **faire `dataclasses.replace()` sur un `AgentDefinition` le perd**.
20. **En construisant `AgentDefinition` directement, les paramètres sont en camelCase** : `maxTurns`,
    `permissionMode`. `worker()` fait déjà la conversion pour vous.

### Handoff et contexte {#陷阱-换代}

21. **Quand le handoff est activé, l'auto-compact est forcé à off, sans filet.** L'étape qui écrit le document de
    handoff doit donc avoir un chemin de dégradation. Pour conserver l'auto-compact, fournissez explicitement
    `AgentSpec.compact`.
22. **Un `HandoffPolicy.window` trop petit provoque des handoffs à l'infini et brûle de l'argent.** Le seul frein
    est `max_generations=8`. À l'autre extrémité, **`default_window()` renvoie aussi `1_000_000` quand aucune des
    deux variables d'environnement n'est définie** — une estimation trop haute est rattrapée par `is_overflow()`
    (ça devient un handoff dégradé) : ce n'est pas une erreur dure, mais le handoff de cette génération est dégradé.
23. **Sans workbench, le handoff n'est pas écrit sur disque.** Le document est tout de même transmis au successeur
    via le prompt, mais l'humain ne pourra pas le retrouver après coup.

### Stockage {#陷阱-存储}

24. **`Runtime(trim=False)` (le défaut) ne signifie pas « on ne nettoie rien ».** Le store est toujours un
    `PruningSessionStore` ; `trim=False` ne désactive que le rognage des gros résultats. **Le retrait des résidus de
    déconnexion, le retrait des appels refusés, la neutralisation des restes d'interruption et l'expiration des
    contenus périssables continuent.**
25. **Les deux répertoires de spill ne sont pas le même** : `spill_guard` tombe dans `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` tombe dans `<workspace>/.flower/spill/` (obligatoirement dans l'espace de travail).
26. **Le quatrième argument positionnel de `PruningSessionStore.__init__` est `prune`, pas `ephemeral`**,
    contrairement à la classe parente. Le passer positionnellement décale silencieusement les arguments.

### Documents et interaction {#陷阱-文书}

27. **Quand `Verdict` n'arrive pas à extraire une conclusion, `state=""` et `ok=False` : cela ne doit jamais être
    pris pour un objectif atteint.** Par ailleurs « 无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable » sont
    tous rangés dans `unreachable`, ce qui déclenche le chemin « s'arrêter et demander à l'humain », pas
    « refaire un tour ».
28. **`Brief.parse` jette tout ce qui suit une clôture de bloc de code non fermée** — quand la sortie du modèle est
    tronquée, les sections suivantes ne sont plus analysables, `complete()` vaut `False`, et le gate renvoie
    l'étape à refaire.
29. **`Brief.load` traite `"(未填)"` comme vide.** Si vous recopiez le texte de remplacement en éditant le brief à
    la main, la section reste considérée comme manquante.
30. **Les trois sémantiques « 0 / None » de `HumanChannel` sont toutes différentes** : `max_asks=None` illimité,
    `max_asks=0` questions interdites ; `timeout_s=None` attente indéfinie, `timeout_s<=0` timeout immédiat ;
    `remaining` renvoie **`-1`** quand `max_asks=None`.
31. **`Event("ask")` porte à la fois les questions et ce que l'humain dit spontanément** ; dans le second cas,
    `payload["kind"] == "mail"`. L'UI doit tester ce champ en premier.
32. **`Workflow.run` ne câble automatiquement que si `channel.on_event is None`** — si vous construisez
    `HumanChannel(on_event=...)` vous-même, les événements de question n'arriveront pas aussi sur la sortie
    `on_event` du workflow.
