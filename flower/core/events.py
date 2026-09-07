"""事件归一化 —— 交互层的解耦边界。

SDK 的消息流是内部类型。任何 UI(Web / TUI / HTTP 服务 / notebook)都不应该
直接依赖它们,否则 SDK 一升级你的前端就跟着改。这里把消息流压平成一组稳定的
Event,UI 只认 Event。

这是"定制交互方式"的落点:换 UI 只需要换 Event 的消费者。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    ResultMessage,
    SystemMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

EventKind = Literal[
    "text", "thinking", "tool_call", "tool_result",
    "task", "system", "reset", "result", "error", "retry", "prompt", "ask",
    "step",      # 步骤边界。由 Workflow.run 发,不来自 normalize ——
                 # UI 靠它画出运行的骨架(确认需求 → 设定目标 → 干活 → 判定)
    "unknown",
]
# "ask" 不由 normalize() 产生 —— 它来自 core/human.py 的提问通道。
# 放在同一个 Literal 里是有意的:UI 只认一套 Event,不必为"要人回答"另开一条路。


@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str:
        if self.kind == "tool_call":
            return f"[{self.tool}] {self.text}"
        return self.text or f"<{self.kind}>"


def _block_to_event(block: Any) -> Event | None:
    if isinstance(block, TextBlock):
        return Event("text", text=block.text, raw=block)
    if isinstance(block, ThinkingBlock):
        return Event("thinking", text=getattr(block, "thinking", ""), raw=block)
    if isinstance(block, ToolUseBlock):
        inp = block.input or {}
        # 给 UI 一个可读摘要,不用它自己解析每种工具的参数
        summary = inp.get("file_path") or inp.get("command") or inp.get("pattern") or ""
        return Event("tool_call", text=str(summary)[:200], tool=block.name,
                     payload={"id": block.id, "input": inp}, raw=block)
    if isinstance(block, ToolResultBlock):
        content = block.content
        text = content if isinstance(content, str) else ""
        return Event("tool_result", text=text[:500],
                     payload={"tool_use_id": block.tool_use_id,
                              "is_error": bool(getattr(block, "is_error", False))},
                     raw=block)
    return None


def _is_api_error(message: Any) -> bool:
    """断线时 harness 塞进 transcript 的合成 assistant 消息。

    它长得像模型说的话,但不是 —— model 是 "<synthetic>"。必须在这里就分流成
    kind="error",否则会被当成正文进 StepResult.text,再顺着 workflow 传给下一步。
    """
    if getattr(message, "isApiErrorMessage", None):
        return True
    raw = getattr(message, "raw", None) or getattr(message, "_raw", None)
    if isinstance(raw, dict):
        if raw.get("isApiErrorMessage"):
            return True
        if isinstance(raw.get("message"), dict) and raw["message"].get("model") == "<synthetic>":
            return True
    return getattr(message, "model", None) == "<synthetic>"


def normalize(message: Any) -> list[Event]:
    """把一条 SDK 消息转成 0..N 个 Event。"""
    if isinstance(message, AssistantMessage) and _is_api_error(message):
        content = message.content
        text = content if isinstance(content, str) else "".join(
            b.text for b in content if isinstance(b, TextBlock))
        return [Event("error", text=text, payload={"synthetic": True}, raw=message)]

    if isinstance(message, (AssistantMessage, UserMessage)):
        # subagent 的消息带 parent_tool_use_id(= 派它出去那次 Agent 调用的 id)。
        # 标出来,消费方才能只收主线程的正文 —— 否则派活的 prompt 和 subagent 的
        # 中间发言会混进 StepResult.text,再顺着 workflow 污染下一步。
        sub = getattr(message, "parent_tool_use_id", None)
        meta = {"subagent": bool(sub)} | ({"parent_tool_use_id": sub} if sub else {})
        # 这一轮模型实际看到多少上下文。**长程运行最该被看见的数字** ——
        # 它决定还能跑多久(实测斜率约 2.2K/轮,1M 窗口约 440 轮撞墙,
        # 见 docs/case-ht001.md 第二节)。此前它只存在于 transcript 里,
        # 事件流拿不到,于是终端上看不见。
        if (u := getattr(message, "usage", None)):
            g = u.get if isinstance(u, dict) else (lambda k, d=0: getattr(u, k, d))
            meta["context"] = (g("input_tokens", 0) + g("cache_read_input_tokens", 0)
                               + g("cache_creation_input_tokens", 0))
        content = message.content
        # UserMessage 的正文是**输入**(用户 prompt / 派给 subagent 的任务书),
        # 不是模型产出。归到 "prompt",不进正文。
        kind: EventKind = "prompt" if isinstance(message, UserMessage) else "text"
        if isinstance(content, str):
            return [Event(kind, text=content, payload=meta, raw=message)]
        out = []
        for b in content:
            if (e := _block_to_event(b)) is not None:
                if e.kind == "text":
                    e.kind = kind
                e.payload |= meta
                out.append(e)
        return out

    if isinstance(message, ResultMessage):
        return [Event("result", text=str(getattr(message, "subtype", "")),
                      payload={
                          "session_id": getattr(message, "session_id", None),
                          "cost_usd": getattr(message, "total_cost_usd", None),
                          "num_turns": getattr(message, "num_turns", None),
                          "is_error": getattr(message, "is_error", None),
                      }, raw=message)]

    if isinstance(message, (TaskStartedMessage, TaskProgressMessage, TaskUpdatedMessage)):
        return [Event("task", text=type(message).__name__, raw=message)]

    if isinstance(message, ConversationResetMessage):
        return [Event("reset", text="conversation reset", raw=message)]

    if isinstance(message, SystemMessage):
        sub = str(getattr(message, "subtype", ""))
        data = getattr(message, "data", {}) or {}
        if sub in ("compact_boundary", "microcompact_boundary"):
            # 压缩边界:此刻之前的消息已被一条摘要替代。长程运行必须能看见它 ——
            # 边界之后模型"记得"的只有摘要,prompt 缓存也从这里断开。
            meta = data.get("compact_metadata") or data.get("compactMetadata") or {}
            pre = meta.get("pre_tokens", meta.get("preTokens"))
            post = meta.get("post_tokens", meta.get("postTokens"))
            trigger = meta.get("trigger", "?")
            micro = sub.startswith("micro")
            return [Event(
                "reset",
                text=f"{'微压缩' if micro else '压缩'}({trigger}) {pre} → {post} tokens",
                payload={"trigger": trigger, "pre_tokens": pre,
                         "post_tokens": post, "micro": micro, "subtype": sub},
                raw=message,
            )]
        return [Event("system", text=sub, payload=dict(data), raw=message)]

    return [Event("unknown", text=type(message).__name__, raw=message)]
