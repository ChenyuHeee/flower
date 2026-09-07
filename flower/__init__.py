"""flower —— 基于 Claude Agent SDK 的可移植长程 agent 框架。"""

from .core.agent import AgentSpec, CompactPolicy, build_options
from .core.brief import Brief
from .core.goal import Goal, Verdict
from .core.events import Event, normalize
from .core.human import Ask, HumanChannel
from .core.guard import (delegate_guard, index_guard, isolate_guard, isolated, merge_hooks,
                         spill_guard, wants_isolation, whitelist_guard, workbench_hooks)
from .core.roles import (CLARIFIER_RULES, COORDINATOR_RULES, JUDGE_RULES, ORACLE_RULES,
                         WORKER_RULES, clarify, coordinator, judge, oracle, worker)
from .core.workbench import Workbench
from .core.runtime import Runtime, StepResult
from .core.resilience import Resilience, classify, endpoint, reachable
from .stores.prune import PrunePolicy, PruningSessionStore
from .stores.sqlite import SqliteSessionStore
from .stores.trim import EphemeralPolicy, is_ephemeral, TrimmingSessionStore, TrimPolicy, trim_report
from .workflow.base import Step, StepAbort, Workflow
from .workflow.clarify import BRIEF_KEY, MISSING_KEY, clarify_step
from .workflow.goal import GOAL_KEY, ROUND_KEY, VERDICT_KEY, goal_step, with_goal
from .workflow.starter import starter_flow

__all__ = [
    "AgentSpec", "CompactPolicy", "build_options",
    "Event", "normalize",
    "Ask", "HumanChannel", "Brief", "Goal", "Verdict",
    "Workbench", "coordinator", "worker", "clarify", "judge", "oracle",
    "COORDINATOR_RULES", "WORKER_RULES", "CLARIFIER_RULES", "JUDGE_RULES", "ORACLE_RULES",
    "delegate_guard", "spill_guard", "index_guard", "workbench_hooks", "merge_hooks",
    "isolate_guard", "isolated", "wants_isolation", "whitelist_guard",
    "Runtime", "StepResult",
    "Resilience", "classify", "endpoint", "reachable",
    "SqliteSessionStore", "TrimmingSessionStore", "TrimPolicy", "EphemeralPolicy",
    "is_ephemeral", "trim_report",
    "PruningSessionStore", "PrunePolicy",
    "Step", "Workflow", "StepAbort", "clarify_step", "BRIEF_KEY", "MISSING_KEY",
    "goal_step", "with_goal", "GOAL_KEY", "VERDICT_KEY", "ROUND_KEY",
    "starter_flow",
]
__version__ = "0.1.0"
