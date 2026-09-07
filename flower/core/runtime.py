"""执行核心 —— 长程 workflow 的运行时。

长程的三个原语,都由 session 血缘提供:
  * **续跑**  resume=<session_id>            —— 保留全部上下文继续
  * **分叉**  resume + fork=True             —— 从某次运行分出新分支,原分支不动
  * **回滚**  resume + resume_at=<msg_uuid>  —— 回到历史某条消息处重来

每个 step 的 session_id 都被记录下来,所以任意一步事后都能被续跑/分叉/回滚。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import anyio
from claude_agent_sdk import query

from .agent import AgentSpec, build_options
from .env import check_credentials, load_dotenv
from .events import Event, normalize
from .guard import merge_hooks, workbench_hooks
from .resilience import Resilience, classify
from .workbench import Workbench
from ..stores.sqlite import SqliteSessionStore
from ..stores.prune import PrunePolicy, PruningSessionStore
from ..stores.trim import EphemeralPolicy, TrimPolicy


def _project_key(path: Path) -> str:
    return str(Path(path).resolve()).replace("/", "-").replace("_", "-").replace(".", "-")


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
    """实际尝试次数。>1 说明中途重试过 —— 只记在 manifest 里,不进上下文。"""
    errors: list[str] = field(default_factory=list)
    """历次失败原因。故障排查看这里,模型看不到。"""
    resumed: bool = False
    """是否靠 resume 从中断处接上(而不是重头跑)。"""

    @property
    def duration_s(self) -> float:
        return round(self.ended_at - self.started_at, 2)


class Runtime:
    """持有工作区、存储与运行记录。UI 通过 on_event 回调接管展示。"""

    def __init__(
        self,
        *,
        workspace: str | Path,
        run_dir: str | Path = "runs",
        portable: bool = True,
        trim: TrimPolicy | bool = False,
        ephemeral: "EphemeralPolicy | bool" = True,
        keep_denials: int = 1,
        workbench: Workbench | bool = False,
        spill_threshold: int | None = 4000,
        resilience: Resilience | bool = True,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.portable = portable
        # trim=True/TrimPolicy:resume 时把旧的大工具结果换成文件指针,
        # 保留全部交互历史。见 stores/trim.py。
        # 默认就用 PruningSessionStore:断线残渣("API Error: ..." 那条合成消息)
        # 在 load 时摘掉,所以 resume 不会把故障当成对话喂回模型。
        # trim 关掉时 policy.enabled=False —— 裁剪不做,摘除照做。
        policy = trim if isinstance(trim, TrimPolicy) else TrimPolicy(enabled=bool(trim))
        # 时效性剪枝默认开:它和 coordinator(glance=True) 是一对 ——
        # 放行主 agent 自己跑 git status,就得保证那些结果会过期。
        eph = (ephemeral if isinstance(ephemeral, EphemeralPolicy)
               else EphemeralPolicy(enabled=bool(ephemeral)))
        # 被拒的工具调用:调用和结果一起摘掉,只留最近 keep_denials 次。
        # 它没执行过,结果里没有信息;留着既费 token 又会把模型教成
        # "Bash 反正会被拦"(实测过,连放行的 git status 都不再尝试了)。
        self.store = PruningSessionStore(
            self.run_dir / "sessions.db", workspace=self.workspace,
            policy=policy, ephemeral=eph,
            prune=PrunePolicy(keep_denials=keep_denials))
        self.resilience = (resilience if isinstance(resilience, Resilience)
                           else Resilience(enabled=bool(resilience)))
        self.results: list[StepResult] = []

        # 工作台:脚本/产出/笔记落到磁盘,索引注入 system prompt。
        # 它承担的是"别重写、别贴回来"这两件事,和压缩无关 —— 压缩清得掉上下文,
        # 清不掉磁盘,也清不掉 system prompt 里的索引。
        self.workbench: Workbench | None = None
        if workbench:
            if isinstance(workbench, Workbench):
                self.workbench = workbench
            else:
                # 默认把工作台放到 run_dir 下(工作区外)。理由:开 worktree 隔离后,
                # 被隔离的 agent 写不进共享 checkout,而工作台恰恰是要跨 agent 共享的。
                # 放外面则两种模式都能用,不用记着切换。
                self.workbench = Workbench(self.workspace, home=self.run_dir / "workbench")
            self.workbench.refresh()
        self.spill_threshold = spill_threshold

        # 可移植性的另一半:凭证由 flower 自带,不来自 ~/.claude/settings.json
        load_dotenv()
        if err := check_credentials():
            raise RuntimeError(err)

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
    ) -> StepResult:
        name = step_name or spec.name
        result = StepResult(step=name, started_at=time.time())
        r = self.resilience
        attempt, cur_prompt, cur_resume, cur_fork = 0, prompt, resume, fork
        while True:
            attempt += 1
            result.attempts = attempt
            await self._attempt(spec, cur_prompt, result, resume=cur_resume,
                                fork=cur_fork, resume_at=resume_at, on_event=on_event)
            if result.ok or not r.enabled or attempt >= r.max_attempts:
                break
            kind = classify(result.error)
            if not r.should_retry(kind):
                break

            note = self._notifier(on_event, name, attempt)
            note(f"第 {attempt} 次失败({kind}),准备重试")
            # 探针:断网就挂着等,不烧钱不烧 token。通了才重试。
            if not await r.wait_online(note):
                result.error = f"{result.error} | 网络在 {r._human_wait()} 内未恢复"
                break
            await anyio.sleep(r.delay_for(attempt))
            # 拿到过 session_id 就续跑,而不是重头来 —— 之前的花费和进度都还在。
            if result.session_id:
                cur_resume, cur_fork, cur_prompt = result.session_id, False, r.resume_prompt
                result.resumed = True

        result.ended_at = time.time()
        self.results.append(result)
        self._persist()
        return result

    @staticmethod
    def _notifier(on_event, step: str, attempt: int):
        def note(msg: str) -> None:
            if on_event:
                on_event(Event("retry", text=msg, payload={"step": step, "attempt": attempt}))
        return note

    async def _attempt(
        self,
        spec: AgentSpec,
        prompt: str,
        result: StepResult,
        *,
        resume: str | None,
        fork: bool,
        resume_at: str | None,
        on_event: Callable[[Event], None] | None,
    ) -> None:
        """跑一次。成功与否写进 result,不抛异常。"""
        prelude = ""
        if self.workbench is not None:
            # 每一步开跑前重扫一次:上一步 subagent 写的脚本,这一步开局就该知道。
            self.workbench.refresh()
            # spec.workbench=False:hook 照挂(spill 对它的 Read 仍有用),
            # 只是不注入索引 —— 没有写工具的角色执行不了那些规矩。
            prelude = self.workbench.prompt_block() if spec.workbench else ""
            hooks = merge_hooks(spec.hooks, workbench_hooks(
                self.workbench,
                delegate_only=spec.delegate_only,
                spill_threshold=self.spill_threshold,
                agents=spec.agents,
                allow_glance=spec.glance,
            ))
            spec = replace(spec, hooks=hooks)
        # 工作台在工作区外时,得显式授权 —— 不然写不进去(实测踩过)。
        extra = ([str(self.workbench.root)]
                 if self.workbench is not None and self.workbench.external else None)
        options = build_options(
            spec,
            prelude=prelude,
            cwd=self.workspace,
            add_dirs=extra,
            session_store=self.store,
            resume=resume,
            fork=fork,
            resume_at=resume_at,
            portable=self.portable,
        )

        texts: list[str] = []
        result.ok, result.error = False, None
        try:
            async for message in query(prompt=prompt, options=options):
                for ev in normalize(message):
                    if on_event:
                        on_event(ev)
                    if ev.kind == "text" and not ev.payload.get("subagent"):
                        # 只收主线程的正文。subagent 的发言留在它自己的 transcript,
                        # 派给它的任务书是 kind="prompt",两者都不进 StepResult.text。
                        texts.append(ev.text)
                    elif ev.kind == "error":
                        # 合成的 API 错误消息:记进 errors,**不进 texts** ——
                        # 它不该出现在 StepResult.text 里被传给下一步。
                        result.errors.append(ev.text)
                    elif ev.kind == "result":
                        result.session_id = ev.payload.get("session_id")
                        # 累加:重试过的 step,前几次的钱也花掉了,账要算全
                        result.cost_usd += ev.payload.get("cost_usd") or 0.0
                        result.num_turns += ev.payload.get("num_turns") or 0
                        result.ok = not ev.payload.get("is_error")
        except Exception as exc:  # noqa: BLE001 - 记录后由重试/workflow 层决策
            result.error = f"{type(exc).__name__}: {exc}"
            result.ok = False

        if not result.ok and not result.error and result.errors:
            result.error = result.errors[-1]
        if not result.errors or result.ok or texts:
            # 失败时保留上一次的正文,不要被空结果冲掉
            result.text = "\n".join(texts).strip() or result.text

    def _persist(self) -> None:
        """运行清单:step → session_id 的血缘,事后 resume/fork 靠它。

        ``duration_s`` 要手工补:它是 ``@property``,而 ``asdict()`` 只收 dataclass
        字段 —— 不补的话清单里没有时长,得自己拿 started_at/ended_at 去减。
        """
        rows = [{**asdict(r), "duration_s": r.duration_s} for r in self.results]
        (self.run_dir / "manifest.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def project_key(self) -> str:
        """SDK 用 cwd 推导 project_key(`/`、`_`、`.` 全部换成 `-`),
        调用方指定不了。查库时必须用这个,不是自定义标签。"""
        return _project_key(self.workspace)

    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.results), 4)

    def close(self) -> None:
        self.store.close()
