"""网络抖动与 API 错误 —— 探针、重试、以及"错误不进上下文"。

长程 workflow 一跑就是几小时,网络必然会断一次。默认行为很糟:

  * 断线那一刻,harness 会往 transcript 里塞一条 **合成 assistant 消息**
    (``model="<synthetic>"``、``isApiErrorMessage=true``),正文就是
    "API Error: Can't reach the API server ...";
  * 这条消息成了会话的叶子。之后 resume,它就被当成"模型上一句说的话"喂回去 ——
    模型会以为自己在讨论网络故障;
  * 它还会混进 ``StepResult.text``,顺着 workflow 传给下一步的 prompt。

所以这里做三件事,缺一不可:

1. **探针**:只做 DNS + TCP,不花钱、不消耗 token。断网时挂在那儿等,通了再继续。
2. **续跑而不是重来**:失败时 session_id 已经拿到了,用 resume 从中断处接上,
   之前的花费不白费。
3. **错误不进上下文**:合成错误消息在 :mod:`flower.stores.prune` 里于 load 时摘掉并重接
   parentUuid;事件流里它是 ``kind="error"`` 而不是 ``"text"``,不进 ``StepResult.text``。

区分可重试与不可重试很重要:网络抖动该等,凭证错该立刻停 —— 断网时死等是对的,
key 写错了死等就是烧时间。
"""

from __future__ import annotations

import os
import random
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import anyio

# 可重试:网络层 + 服务端临时故障。
TRANSIENT = re.compile(
    r"ENOTFOUND|EAI_AGAIN|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EPIPE|EHOSTUNREACH|ENETDOWN"
    r"|socket hang up|fetch failed|network error|Connection error|Can't reach the API server"
    r"|\b(?:429|500|502|503|504|529)\b|overloaded|rate.?limit|too many requests"
    r"|timeout|timed out|temporarily unavailable|service unavailable|internal server error",
    re.IGNORECASE,
)

# 不可重试:重试多少次结果都一样,而且每次都要钱。
FATAL = re.compile(
    r"\b(?:400|401|403|404)\b|invalid.?api.?key|authentication|unauthorized|permission denied"
    r"|invalid_request|credit balance|quota exceeded|budget|max_turns|CLINotFound",
    re.IGNORECASE,
)


def classify(text: str | None) -> str:
    """``"transient"`` | ``"fatal"`` | ``"unknown"``。

    先判 fatal:401 之类的文本里常常也带着 "connection" 这种词,顺序反了会死等。
    """
    if not text:
        return "unknown"
    if FATAL.search(text):
        return "fatal"
    if TRANSIENT.search(text):
        return "transient"
    return "unknown"


def endpoint() -> tuple[str, int]:
    """当前生效的 API 端点 (host, port)。跟着 ANTHROPIC_BASE_URL 走 —— 探自建网关时
    必须探它,而不是探 api.anthropic.com:后者通说明不了前者通。"""
    url = os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
    u = urlparse(url if "://" in url else f"https://{url}")
    return u.hostname or "api.anthropic.com", u.port or (80 if u.scheme == "http" else 443)


async def reachable(host: str, port: int, timeout: float = 5.0) -> bool:
    """DNS + TCP 握手。不发 HTTP、不带凭证、不花钱 —— 探针必须免费,
    否则"断网时每 10 秒探一次"本身就成了故障。"""
    try:
        with anyio.fail_after(timeout):
            await anyio.to_thread.run_sync(socket.getaddrinfo, host, port)
            stream = await anyio.connect_tcp(host, port)
            await stream.aclose()
        return True
    except Exception:  # noqa: BLE001 —— 任何失败都算不可达
        return False


@dataclass
class Resilience:
    """重试与探针策略。默认值针对"跑几小时、家里网偶尔抖一下"这种场景。"""

    enabled: bool = True
    max_attempts: int = 6
    """一个 step 最多尝试几次(含首次)。"""

    base_delay: float = 4.0
    max_delay: float = 120.0
    """指数退避;带 ±25% 抖动,避免恢复瞬间一起冲上去。"""

    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    """断网最多等多久。默认 1 小时 —— 长过这个,通常不是抖动而是真出事了。"""

    retry_unknown: bool = True
    """分类不出来的错误也重试一次。多数未知错误是瞬时的,而 fatal 已经被单独挡住了。"""

    resume_prompt: str = (
        "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,"
        "从中断处接着做,不要重头来过。"
    )
    """续跑时说的话。**有意不含任何错误细节** —— 模型需要知道"被打断了、接着做",
    不需要知道是 ENOTFOUND 还是 503。那属于日志,不属于上下文。"""

    def _human_wait(self) -> str:
        w = self.max_offline_wait
        return f"{w:.0f} 秒" if w < 60 else f"{w/60:.0f} 分钟"

    def delay_for(self, attempt: int) -> float:
        d = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return d * (0.75 + random.random() * 0.5)

    def should_retry(self, kind: str) -> bool:
        return kind == "transient" or (kind == "unknown" and self.retry_unknown)

    async def wait_online(self, notify=None) -> bool:
        """挂在这里等网络回来。回来了返回 True,等到超时返回 False。"""
        host, port = endpoint()
        deadline = time.monotonic() + self.max_offline_wait
        first = True
        while time.monotonic() < deadline:
            if await reachable(host, port, self.probe_timeout):
                if notify and not first:
                    notify(f"{host}:{port} 恢复,继续")
                return True
            if first and notify:
                notify(f"{host}:{port} 不可达,等待恢复(最多 {self._human_wait()})")
            first = False
            await anyio.sleep(self.probe_interval)
        return False
