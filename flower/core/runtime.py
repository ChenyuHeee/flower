"""执行核心 —— 长程 workflow 的运行时。

长程的三个原语,都由 session 血缘提供:
  * **续跑**  resume=<session_id>            —— 保留全部上下文继续
  * **分叉**  resume + fork=True             —— 从某次运行分出新分支,原分支不动
  * **回滚**  resume + resume_at=<msg_uuid>  —— 回到历史某条消息处重来

每个 step 的 session_id 都被记录下来,所以任意一步事后都能被续跑/分叉/回滚。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import anyio
from claude_agent_sdk import query

from .agent import AgentSpec, CompactPolicy, HandoffPolicy, build_options
from .env import check_credentials, load_dotenv
from .events import Event, normalize
from .handoff import HANDOFF_PROMPT, Handoff, degraded, is_overflow
from .guard import merge_hooks, whitelist_guard, workbench_hooks
from .resilience import Resilience, classify
from .workbench import Workbench
from ..stores.sqlite import SqliteSessionStore
from ..stores.prune import PrunePolicy, PruningSessionStore
from ..stores.trim import EphemeralPolicy, TrimPolicy


class _Overflow(Exception):
    """内部信号:这个会话已经装不下了,别再试着让它写交接。"""


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
    retired: list[str] = field(default_factory=list)
    """这一步换代时烧掉的 session_id,按顺序。

    ``session_id`` 永远是**最后接班的那个**(血缘要指向还活着的会话),
    所以被换掉的那几代只能记在这里。事后追溯一次长跑靠它。"""
    context: int = 0
    """最后一轮主线程实际看到的上下文规模。换代判据,也给 UI。"""

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
        handoff: "HandoffPolicy | bool" = True,
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
        # 上下文快满了:写交接换新会话,而不是 compact。见 core/handoff.py。
        self.handoff = (handoff if isinstance(handoff, HandoffPolicy)
                        else HandoffPolicy(enabled=bool(handoff)))
        self._ctx = 0            # 本次 _attempt 里主线程见过的最大上下文
        self._warned = False     # 逼近提醒每代只发一次
        self._writing_handoff = False   # 见 _handoff_due:写交接那一轮豁免阈值
        self.results: list[StepResult] = []
        # 这次进程的标记 + 上次留下的账。manifest 是**跨进程累积**的:
        # 同一个目录接着跑(见 core/lineage.py),它就是唯一能查到
        # "哪一步用了哪个 session" 的地方,不能被后一次运行冲掉。
        # **必须每个实例唯一**,不能只是秒级时间戳:_persist 按 run 去重,
        # 两个 id 撞上时后写的会把对方的行当成"自己上次写的"删掉(实测踩过)。
        # 时间戳给人看,后缀保证唯一 —— 同一秒启动的两个进程也不会撞。
        self.run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self._prior_rows = self._load_manifest()   # 只用于启动时了解已有多少行
        self._interrupt: str | None = None
        """人按下 Ctrl+C 时想说的话。见 :meth:`interrupt`。"""
        self.on_session: "Callable[[str], None] | None" = None
        """拿到新 session_id 时立刻回调。血缘用它,好在进程被硬杀前就落盘。
        **只该罩在 runtime.run 这一句上**(见 workflow/base.py):判定者用的是
        同一个 Runtime,gate 期间还挂着的话会把判定者的 session 写进干活的血缘,
        「判定者永远是新会话」这条不变式当场破掉。"""
        self._current: "StepResult | None" = None
        """正在飞的这一步。SIGHUP 处理器要靠它把在飞的账也落一份。"""

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

    INTERRUPTED = "interrupted-by-human"
    HANDOFF_DUE = "context-full-handoff"

    def interrupt(self, message: str = "") -> None:
        """人要打断当前这一轮。**任何线程都能调**(UI 通常在别的线程)。

        为什么必须有这个:在此之前 Ctrl+C 直接杀进程 —— 一次十小时的运行
        会被肌肉记忆干掉。那比"没有打断功能"更糟。

        做法上复用了断网重试那条现成的路(见 :meth:`run` 的循环):
        把"失败原因"换成"人打断了",把 ``resume_prompt`` 换成人说的话,
        于是它 **resume 同一个 session 接着跑**,已经干完的活和上下文都在。

        是**协作式**的:在消息循环里检查,在消息边界干净地断开,
        而不是硬取消任务。代价是延迟到下一条消息 —— subagent 正跑着的话
        可能要等它回来。换来的是不会在半路撕裂状态。

        空字符串 = 只打断,不说话(等价于"停一下,我看看")。
        """
        self._interrupt = message or ""

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
        self._current = result        # SIGHUP 时要靠它把在飞的账也落一份
        # 水位是**每一步**的:上一步在 150K 收尾,这一步是新会话,不能一开局
        # 就被上一步的读数逼着换代。(漏掉这一句的后果是第二步立刻空转换代。)
        self._ctx, self._warned = 0, False
        r = self.resilience
        attempt, cur_prompt, cur_resume, cur_fork = 0, prompt, resume, fork
        while True:
            attempt += 1
            result.attempts = attempt
            await self._attempt(spec, cur_prompt, result, resume=cur_resume,
                                fork=cur_fork, resume_at=resume_at, on_event=on_event)
            if result.ok:
                break
            # 人打断:不受 max_attempts 约束(那是给故障用的),也不用等网络。
            # 直接带着他的话 resume 同一个 session —— 已经干完的活都还在。
            if result.error == self.INTERRUPTED:
                said, self._interrupt = self._interrupt, None
                if not result.session_id:
                    break            # 还没拿到 session,没法续 —— 只能停下
                note = self._notifier(on_event, name, attempt)
                note("已打断,带着你的话续跑" if said else "已打断,继续跑")
                cur_resume, cur_fork = result.session_id, False
                cur_prompt = (f"人在这里打断了你,说:\n\n{said}\n\n"
                              "按这句话调整,接着做 —— 不要重头开始。"
                              if said else r.resume_prompt)
                result.resumed = True
                attempt -= 1          # 打断不算一次失败尝试
                continue
            # 上下文满了:写交接,换一个新会话接手 —— 不 compact。
            # 和打断一样不受 max_attempts 约束:换代不是故障。
            # 装不下了。窗口是按模型名判的,判大了的话阈值永远够不着 ——
            # 而 auto-compact 是关的。认出这个信号就能把硬错变成一次换代。
            overflowed = (self.handoff.enabled and result.session_id
                          and is_overflow(result.error, *result.errors))
            if result.error == self.HANDOFF_DUE or overflowed:
                if len(result.retired) >= self.handoff.max_generations:
                    # 阈值低于这个 agent 的启动地板时,每个新会话一开口就越线,
                    # 于是永远换代下去(换代不吃重试额度)。这里是那道闸。
                    result.error = (
                        f"换代 {len(result.retired)} 次仍然一开局就越线 —— "
                        f"阈值 {self.handoff.at} 很可能低于这个角色的启动地板。"
                        f"把 window 调大(现在 {self.handoff.window}),或 --no-handoff。")
                    break
                retiring = result.session_id
                # 已经装不下的会话跑不动"再写一轮交接" —— 直接用机械拼的降级件。
                h = await self._write_handoff(spec, prompt, result, on_event,
                                              forced=overflowed)
                if retiring:
                    result.retired.append(retiring)
                cur_resume, cur_fork = None, False       # ← 全新会话,这是重点
                cur_prompt = h.prompt_block()
                result.session_id = None                 # 新会话会带来新的
                self._ctx, self._warned = 0, False       # 水位跟着归零
                attempt -= 1
                continue
            if not r.enabled or attempt >= r.max_attempts:
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
        self._current = None
        self.results.append(result)
        self._persist()
        return result

    @staticmethod
    def _notifier(on_event, step: str, attempt: int):
        def note(msg: str) -> None:
            if on_event:
                on_event(Event("retry", text=msg, payload={"step": step, "attempt": attempt}))
        return note

    def _handoff_due(self, result: StepResult) -> bool:
        """这一轮该换代了吗。

        ``_writing_handoff`` 那个豁免不是小节 —— **漏掉它这套机制根本不工作**:
        写交接是在越线之后、水位还挂在阈值之上的时候跑的,不豁免的话它第一条
        消息就又判"该换代了",于是交接一个字都没写出来就被打断,每次都降级。
        (实测:`tests/handoff_live.py` 头一次真跑,两代交接全是降级版本。
        离线测试没抓到,因为那里把 ``_attempt`` 整个换掉了 —— 假的没跑这条判据。)
        """
        return bool(self.handoff.enabled and not self._writing_handoff
                    and self._ctx >= self.handoff.at and result.session_id)

    def _maybe_warn(self, on_event, step: str) -> None:
        """逼近换代时提醒**一次**。每代只发一次,不刷屏。"""
        h = self.handoff
        if not (h.enabled and not self._warned and self._ctx >= h.warn_at):
            return
        self._warned = True
        if on_event:
            on_event(Event("handoff", text=(
                f"上下文 {self._ctx / 1000:.1f}K/{h.window / 1000:.0f}K · "
                f"还有约 {max(0, h.at - self._ctx) / 1000:.0f}K 到换代"),
                payload={"phase": "near", "step": step, "context": self._ctx,
                         "window": h.window, "at": h.at}))

    async def _write_handoff(
        self,
        spec: AgentSpec,
        prompt: str,
        result: StepResult,
        on_event: Callable[[Event], None] | None,
        forced: bool = False,
    ) -> Handoff:
        """让**当前这个会话**写一份交接,冻结到磁盘。

        为什么是它自己写、不另派一个角色:只有它有那段上下文。换谁来写都得
        先把上下文读一遍,那就白换了。

        写不出来时降级(:func:`~flower.core.handoff.degraded`)而**不是停下**:
        换代开着的时候 auto-compact 是关的,没有兵底 —— 停在这里等于撞窗口。
        残缺的交接远胜于硬错。
        """
        h = self.handoff
        before, name = self._ctx, result.step
        probe = StepResult(step=name, session_id=result.session_id)
        # 先说一声。写交接要十几秒,这段时间界面上一个字都没有 —— 看起来像卡住,
        # 而用户明确要求这个过程是他知道的。
        if on_event:
            on_event(Event("handoff", text=(
                f"上下文 {before / 1000:.1f}K/{h.window / 1000:.0f}K —— 正在写交接…"),
                payload={"phase": "writing", "step": name,
                         "context": before, "window": h.window}))
        why = "上下文已经装不下,连交接都跑不了一轮" if forced else ""
        self._writing_handoff = True
        try:
            if forced:
                raise _Overflow
            await self._attempt(
                replace(spec, max_budget_usd=None),   # 交接必须写得出来,别卡在预算上
                HANDOFF_PROMPT.format(used=f"{before / 1000:.1f}K",
                                      window=f"{h.window / 1000:.0f}K"),
                probe, resume=result.session_id, fork=False, resume_at=None,
                on_event=None,                        # 这一轮不往 UI 上刷,只出结果
            )
            result.cost_usd += probe.cost_usd
            result.num_turns += probe.num_turns
            doc = Handoff.parse(probe.text or "", step=name)
            if not doc.complete():
                why = f"缺{'/'.join(doc.missing())}"
        except _Overflow:
            doc = Handoff(step=name)                  # why 已经写好了
        except Exception as exc:                      # noqa: BLE001
            doc, why = Handoff(step=name), f"{type(exc).__name__}"
        finally:
            self._writing_handoff = False
        if why:
            doc = degraded(name, prompt, why=why)
            result.errors.append(f"交接降级({why})")

        path = self._handoff_path(name)
        if path is not None:
            doc.write(path)
        if on_event:
            on_event(Event("handoff", text=f"上下文满了,写交接换新会话({name})",
                           payload={"phase": "done", "step": name,
                                    "context": before, "window": h.window,
                                    "degraded": doc.degraded,
                                    "path": str(path) if path else "",
                                    "sections": {k: getattr(doc, k)
                                                 for k in ("doing", "decided",
                                                           "deadends", "next")}}))
        return doc

    def _handoff_path(self, step: str) -> Path | None:
        """交接落在哪。没有工作台就不落盘 —— 文书照样通过 prompt 交给接手的人,
        只是人事后翻不到。"""
        if self.workbench is None:
            return None
        safe = "".join(c for c in step if c not in '/\\:*?"<>|').strip() or "step"
        cur = self.workbench.notes / f"交接-{safe}.md"
        if cur.exists():
            # 上一代的交接收进档案 —— 和 --new 同一套动作,看得见每一代写了什么。
            old_dir = self.workbench.notes / "archive" / "交接"
            old_dir.mkdir(parents=True, exist_ok=True)
            try:
                cur.replace(old_dir / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.md")
            except OSError:
                pass
        return cur

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
        name = result.step
        prelude = ""
        hooks = spec.hooks
        if self.workbench is not None:
            # 每一步开跑前重扫一次:上一步 subagent 写的脚本,这一步开局就该知道。
            self.workbench.refresh()
            # spec.workbench=False:hook 照挂(spill 对它的 Read 仍有用),
            # 只是不注入索引 —— 没有写工具的角色执行不了那些规矩。
            prelude = self.workbench.prompt_block() if spec.workbench else ""
            hooks = merge_hooks(hooks, workbench_hooks(
                self.workbench,
                delegate_only=spec.delegate_only,
                spill_threshold=self.spill_threshold,
                agents=spec.agents,
                allow_glance=spec.glance,
            ))
        if not spec.delegate_only:
            # 让 allowed_tools 对动手工具真正排他。**不依赖工作台** ——
            # 它是安全性质的,不能因为没开 -W 就消失(那是原来的一个洞:
            # hook 整体只在有工作台时才装)。
            #
            # delegate_only 的角色(协调者)不装:delegate_guard 已经拦了同一批工具,
            # 而且它的措辞更对路("去派人"),重复装只会让模型收到两条矛盾的指引。
            if (wall := whitelist_guard(spec.allowed_tools, role=spec.name)) is not None:
                hooks = merge_hooks(hooks, {"PreToolUse": [wall]})
        if hooks is not spec.hooks:
            spec = replace(spec, hooks=hooks)
        if self.handoff.enabled and spec.compact is None:
            # 换代和 auto-compact 同时开着的话,某次上下文回落到底是谁干的
            # 就说不清了。spec 自己显式给了 compact 就尊重它,不覆盖。
            spec = replace(spec, compact=CompactPolicy(mode="no_summary"))
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
                # session_id 尽早抓住:它此前只从末尾那条 result 事件取,
                # 于是**中途打断时根本没有 session 可续**(实测:打断后
                # session_id 是 None,只能停下,十小时的活白干)。
                # 见一条记一条。**注意**:init 系统消息在 Python SDK 里
                # **不带** session_id(SystemMessage 只有 subtype/data),
                # 所以实际最早拿到它是第一条 assistant 消息 —— 已经够早。
                sid = getattr(message, "session_id", None)
                if not sid and isinstance(getattr(message, "data", None), dict):
                    sid = message.data.get("session_id")     # init 的 data 里有
                if sid and sid != result.session_id:
                    result.session_id = sid
                    if self.on_session:
                        # 拿到就立刻落盘 —— 进程被硬杀(终端崩溃 → SIGHUP)时,
                        # "步骤跑完才写血缘"那条根本来不及。见 issue #6。
                        try:
                            self.on_session(sid)
                        except Exception:        # noqa: BLE001 —— 落盘失败不该带走这次运行
                            pass
                if self._handoff_due(result):
                    # 上下文越线。在**消息边界**断开,和打断同一个道理:
                    # 干净地断,不撕裂状态。代价也一样(在飞的 subagent 会丢),
                    # 而 headroom 那 50k 余量正是为这一下留的。
                    result.error = self.HANDOFF_DUE
                    result.ok = False
                    break
                if self._interrupt is not None:
                    # 人按了 Ctrl+C。在消息边界断开 —— 已经收到的都算数,
                    # 正在跑的 subagent 会丢(和断网那次同一个后果,已实测)。
                    result.error = self.INTERRUPTED
                    result.ok = False
                    break
                for ev in normalize(message):
                    if on_event:
                        on_event(ev)
                    # 只看主线程:subagent 的上下文是它自己那条 transcript 的事,
                    # 它跑完就散了,再大也不该逼主会话换代。
                    if (n := ev.payload.get("context")) and not ev.payload.get("subagent"):
                        self._ctx = max(self._ctx, int(n))
                        result.context = self._ctx
                        self._maybe_warn(on_event, name)
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

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    def _load_manifest(self) -> list[dict]:
        """读回上一次(以及更早)留下的行。读不动就当空的 —— 不能因为
        一份坏掉的账本拦住这次运行。"""
        try:
            rows = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

    def rescue(self) -> None:
        """**被硬杀之前**尽量把账落全。

        由 SIGHUP / SIGTERM 处理器调用(终端崩溃时内核发的就是 SIGHUP,
        默认动作是直接终止 —— 见 issue #6:novel 那次连 manifest 都没有)。
        只做同步的小写盘,不试图继续跑:pty 已经没了,再 print 会 EIO。

        在飞的那一步也写进 manifest,标上 ``killed`` —— 事后能看出
        "这一步没跑完,是被外面掐的",而不是无声无息地消失。
        """
        try:
            if (cur := self._current) is not None and cur.ended_at == 0.0:
                cur.ended_at = time.time()
                cur.error = cur.error or "killed-by-signal"
                self.results.append(cur)
                self._current = None
            self._persist()
        except Exception:              # noqa: BLE001 —— 抢救失败也不能再抛
            pass

    def _persist(self) -> None:
        """运行清单:step → session_id 的血缘,事后 resume/fork 靠它。

        **追加,不覆盖。** 以前写的是 ``self.results``,而它每个进程从空列表开始
        且从不读回来 —— 于是在同一个 run_dir 跑第二次,第一次的账被整个冲掉。
        现在每行带 ``run``(进程启动时刻),按它分组就能看出跑了几次。

        ``duration_s`` 要手工补:它是 ``@property``,而 ``asdict()`` 只收 dataclass
        字段 —— 不补的话清单里没有时长,得自己拿 started_at/ended_at 去减。
        """
        # **每次都重读**,不用启动时缓存的那份:同一个目录里并行跑两个 flower 时,
        # 缓存版会让后写的那个把对方这段时间新增的行整个冲掉。
        # 按 run 去重:文件里属于本进程的行是我们上一次写的,换成最新的;
        # 别人的行原样留着。这样并行追加是安全的。
        others = [r for r in self._load_manifest() if r.get("run") != self.run_id]
        rows = others + [
            {**asdict(r), "duration_s": r.duration_s, "run": self.run_id}
            for r in self.results
        ]
        self.manifest_path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def project_key(self) -> str:
        """SDK 用 cwd 推导 project_key(`/`、`_`、`.` 全部换成 `-`),
        调用方指定不了。查库时必须用这个,不是自定义标签。"""
        return _project_key(self.workspace)

    def has_session(self, session_id: str) -> bool:
        """这个 session_id 在**本工作区**下还查得到吗。

        ``project_key`` 由工作区路径推导(见 :attr:`project_key`),所以目录被拷走
        之后旧 id 一律查不到 —— 这正是想要的:接续应该退回从头开始,而不是报错。
        """
        store = getattr(self.store, "has_session", None)
        return bool(store and store(self.project_key, session_id))

    def context_of(self, session_id: str) -> int:
        """某个 session 最后一轮的上下文规模。给唤醒时那行状态用。"""
        fn = getattr(self.store, "last_context", None)
        return int(fn(self.project_key, session_id)) if fn else 0

    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.results), 4)

    def close(self) -> None:
        self.store.close()
