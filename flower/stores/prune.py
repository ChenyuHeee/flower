"""load 时把"不该再喂回模型"的条目摘掉 —— 断线残渣、以及旧的大工具结果。

两类清理,合在同一个 load 钩子里:

* **合成错误消息**(``isApiErrorMessage=true``、``model="<synthetic>"``)。
  断线时 harness 会把 "API Error: ..." 作为一条 assistant 消息写进 transcript。
  它是**日志**,不是对话:留着它 resume,模型会以为自己刚才在谈网络故障。
  SQLite 里原样保留,只是不喂回去。
* **旧的大 tool_result 正文** —— :class:`~flower.stores.trim.TrimPolicy` 那套,原样复用。

摘除的结构性红线只有一条:transcript 是 ``parentUuid`` 单链,
harness 从叶子往回走。**摘掉一条就必须把它的孩子接到它的父亲上**,否则链断在那里,
前面的历史全部丢失 —— 那是比留着错误消息严重得多的故障。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import SessionKey, SessionStoreEntry

from .trim import EphemeralPolicy, TrimmingSessionStore, TrimPolicy


def is_api_error(entry: dict[str, Any]) -> bool:
    """断线/报错时 harness 写下的合成 assistant 消息。"""
    if entry.get("isApiErrorMessage"):
        return True
    msg = entry.get("message")
    return isinstance(msg, dict) and msg.get("model") == "<synthetic>"


def is_denial(entry: dict[str, Any]) -> str | None:
    """被 permission hook 拒掉的工具调用 —— 返回那次调用的 tool_use_id。

    harness 自己打了结构性标记 ``toolDenialKind``,比匹配拒绝语的文案可靠
    (文案随时会改,标记不会)。
    """
    if entry.get("toolDenialKind") != "permission-rule":
        return None
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
            return b["tool_use_id"]
    return None


def drop_blocks(entry: dict[str, Any], ids: set[str]) -> dict[str, Any] | None:
    """从一条消息里摘掉指定 id 的 tool_use / tool_result 块。

    返回 None 表示这条消息被摘空了,该整条丢掉(由调用方 relink)。
    同一条 assistant 消息里可能有多个 tool_use —— 只摘中标的那个,
    其余的照留,否则会把没被拒的调用一起弄丢,变成 "Missing Tool Result Block"。
    文本和 thinking 块保留:那是模型真实的输出,不是死命令。
    """
    msg = entry.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        return entry
    kept = [
        b for b in msg["content"]
        if not (isinstance(b, dict)
                and (b.get("id") in ids if b.get("type") == "tool_use"
                     else b.get("tool_use_id") in ids if b.get("type") == "tool_result"
                     else False))
    ]
    if len(kept) == len(msg["content"]):
        return entry
    if not kept:
        return None
    out = {**entry, "message": {**msg, "content": kept}}
    out.pop("toolUseResult", None)      # 拒绝语在这里还存了一份
    return out


def is_interrupt_result(entry: dict[str, Any]) -> bool:
    """"[Request interrupted ...]" 这类中断残留的 tool_result。

    注意:**只换正文,不摘除条目** —— tool_result 块少一个,API 直接报
    "Missing Tool Result Block"。这里只是识别,处理见 :func:`prune`。
    """
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error")
        and isinstance(b.get("content"), str) and "[Request interrupted" in b["content"]
        for b in content
    )


def relink(entries: list[dict[str, Any]], drop: set[str]) -> list[dict[str, Any]]:
    """摘除 ``drop`` 里的 uuid,并把断掉的 parentUuid 接到最近的存活祖先。

    **``entries`` 必须是完整的列表,包含要摘掉的那些条目** —— 过滤由这里做。
    调用方先把它们剔掉再传进来的话,``parent_of`` 里就查不到被摘条目的父亲,
    ``survivor()`` 只能返回 None,链断在那儿,前面的历史全丢。
    (踩过:被摘条目正好在末尾时不暴露,一旦它中间就炸。)
    """
    if not drop:
        return entries
    parent_of = {e["uuid"]: e.get("parentUuid") for e in entries if e.get("uuid")}

    def survivor(uid: str | None) -> str | None:
        seen: set[str] = set()
        while uid in drop and uid not in seen:
            seen.add(uid)
            uid = parent_of.get(uid)
        return uid

    out = []
    for e in entries:
        if e.get("uuid") in drop:
            continue
        p = e.get("parentUuid")
        if p in drop:
            e = {**e, "parentUuid": survivor(p)}
        out.append(e)
    return out


@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    """摘掉断线/报错的合成消息。"""

    neutralize_interrupts: bool = True
    """中断残留的 tool_result 换成一句中性说明(块保留)。"""

    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"

    keep_denials: int = 1
    """保留最近 N 次被拒的工具调用,更早的连**调用带结果一起**摘掉。

    被拒的调用从来没执行过,结果里没有任何信息 —— 只有一句"你不该这么做"。
    而它占的位置不小:实测一次 273 字符(93 字拒绝语 + 180 字**死命令原文**),
    死命令比拒绝语还贵。这条规矩已经写在 system prompt 里了,上下文里再留一份
    是重复。

    比省 token 更要紧的是**它会误导**:实测协调者读到几条 "不直接使用 Bash"
    之后,连放行的 `git status` 都不再尝试了,直接说"Bash 被限制了,派个 agent
    去看" —— 学成了习得性无助,反而多花一次 subagent 启动。

    默认留 1 条而不是 0:最新那次拒绝是有效信号,能防止模型在同一轮里
    反复重试同一条被拦的命令。"""


class PruningSessionStore(TrimmingSessionStore):
    """在 :class:`TrimmingSessionStore` 之上再摘掉断线残渣。

    Runtime 默认用它 —— 断网是长程运行的常态,不该由使用者自己去装配。
    """

    def __init__(self, path: str | Path, workspace: str | Path,
                 policy: TrimPolicy | None = None,
                 prune: PrunePolicy | None = None,
                 ephemeral: EphemeralPolicy | None = None) -> None:
        super().__init__(path, workspace, policy, ephemeral)
        self.prune_policy = prune or PrunePolicy()
        self.pruned = 0
        self.denials_dropped = 0

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        entries = await super().load(key)   # 先跑 trim
        return entries if entries is None else self.prune(entries)

    def prune(self, entries: list[SessionStoreEntry]) -> list[SessionStoreEntry]:
        pp = self.prune_policy
        out: list[dict[str, Any]] = []
        drop: set[str] = set()

        # 先决定哪些被拒的调用要摘掉 —— 需要按出现顺序看全局,所以先扫一遍。
        denied = [uid for e in entries if (uid := is_denial(e))]
        dead: set[str] = set(denied[:-pp.keep_denials] if pp.keep_denials > 0 else denied)
        self.denials_dropped = len(dead)

        for e in entries:
            if dead:
                # 摘掉死掉的 tool_use / tool_result 块;整条被摘空就丢掉 + relink。
                trimmed = drop_blocks(e, dead)
                if trimmed is None:
                    if uid := e.get("uuid"):
                        drop.add(uid)
                        out.append(e)     # 原样交给 relink 过滤,它需要看到父子关系
                        continue
                else:
                    e = trimmed
            if pp.drop_api_errors and is_api_error(e):
                if uid := e.get("uuid"):
                    drop.add(uid)
                    out.append(e)         # 同上:relink 负责剔除,这里只做标记
                    continue
            if pp.neutralize_interrupts and is_interrupt_result(e):
                msg = dict(e["message"])
                msg["content"] = [
                    {**b, "content": pp.interrupt_text, "is_error": False}
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                       and b.get("is_error") and "[Request interrupted" in str(b.get("content"))
                    else b
                    for b in msg["content"]
                ]
                e = {**e, "message": msg}
            out.append(e)
        self.pruned = len(drop)
        return relink(out, drop)
