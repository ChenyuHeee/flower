"""改写"喂回模型的历史" —— 你真正能控制 compact 规则的那一层。

harness 内置的 compact 在二进制里,改不了。但 `SessionStore.load()` 是
**resume 前唯一的改写点**:SDK 拿它的返回值物化成临时 jsonl,再让子进程从那里恢复。
所以裁什么、留什么,在这里由你说了算。

默认策略正好是你要的:
  * 保留全部交互历史 —— user/assistant 文本、thinking、工具调用记录一条不动
  * 只把**旧的、大的 tool_result 正文**换成一行指针,原文落盘到工作区
  * 模型想看回去,用 Read 读那个文件即可(和 Claude Code 自己的做法一致)

另一条正交的规则:**时效性**。``git status``、``ls``、``ps`` 这类结果很短,
按大小永远轮不到裁,但它们的正确性随时间衰减 —— 20 轮前那份 ``git status``
不是"没用",是**会误导**:模型会拿它当现状用。所以短、且时效性强的结果,
过了 ``EphemeralPolicy.keep_recent`` 轮就换成一句"已过期,需要请重新执行"。
这类内容不落盘 —— 归档一份过期的 ``git status`` 没有任何意义,重跑一次就有了。

SQLite 里的原始 transcript 一个字都不改 —— 这里只影响"喂回模型的那一份"。

两条结构性红线,违反了 API 直接报错:
  1. tool_result **块本身必须在**,只能换 content。少一个就是 "Missing Tool Result Block"
  2. isCompactSummary 条目不能动 —— 它是那段被压掉的历史唯一的存在形式
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import SessionKey, SessionStoreEntry

from .sqlite import SqliteSessionStore


@dataclass
class TrimPolicy:
    """裁剪规则。默认值偏保守:只动"旧且大"的工具结果。"""

    keep_recent: int = 20
    """最近 N 个 tool_result 保留原文 —— 正在用的上下文不该被裁。"""

    min_chars: int = 2000
    """短结果不值得裁,换成指针反而更费 token。"""

    spill_dirname: str = ".flower/spill"
    """归档目录,相对 workspace。必须在工作区内,否则 agent 的 Read 够不到。"""

    enabled: bool = True

    def placeholder(self, path: str, n: int) -> str:
        return (
            f"[工具结果已归档:{n} 字符。完整内容在 {path},需要时用 Read 读取]"
        )


# 结果只反映"此刻"的命令:重跑一次就有,存下来反而有害。
# 这里判的是命令本身,不是输出 —— 输出长什么样无所谓,关键是它描述的是瞬时状态。
#
# **这张表同时是"还给主 agent 的权限清单"**:core/guard.py 的 delegate_guard
# (allow_glance=True)也走 :func:`is_ephemeral` 来决定放行哪些命令。两件事必须是
# 同一个来源 ——
#   放行了但不剪枝 → 过期的 git status 永久占着上下文,还会误导
#   剪枝了但不放行 → 主 agent 为一条 ls 派个 subagent,4.3k 启动成本换几十字符
# 加一条命令进来,等于同时说"主 agent 可以自己跑"和"结果会过期"。别只改一边。
#
# `echo` 在表里是因为模型习惯拿它当分隔标签写
# (`git status && echo "--- LOG ---" && git log`)。它本身无副作用,
# 不放进来的话这类复合命令整条都会被拒。
EPHEMERAL_CMD = re.compile(
    r"""^\s*(?:
        git\s+(?:status|diff|log|show|branch|stash\s+list|worktree\s+list|remote|
                 rev-parse|describe|ls-files|blame|shortlog|reflog|cherry|
                 for-each-ref|symbolic-ref|whatchanged|hash-object|cat-file|
                 count-objects|check-ignore|var|config\s+--get)\b
      | (?:ls|ll|dir|pwd|df|du|free|uptime|date|whoami|hostname|id|env|printenv)\b
      | (?:ps|top|htop|jobs|lsof|netstat|ss|pgrep|systemctl\s+status|
           docker\s+(?:ps|images|stats)|kubectl\s+get)\b
      | (?:cat|head|tail|wc|stat|file|find|tree|echo)\b
      # 过滤/整形:模型几乎总是把它们接在管道后面(`ps aux | grep py | head`)。
      # 只读 —— 会写文件的那几个形式(sed -i / sort -o / tee)在 _MUTATES 里拦掉。
      | (?:grep|egrep|fgrep|rg|sort|uniq|cut|tr|awk|sed|column|jq|nl|rev|comm|diff)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# 命令替换、进程替换 —— 里面可以是任意命令,逐段检查证明不了安全。
_SUBST = re.compile(r"\$\(|`|<\(|>\(")

# 会改状态的动作,即使动词在白名单里也要拦(`find . -delete`、`find -exec rm`)。
# 白名单里的动词也可能带上会改状态的选项 —— 这些必须单独拦掉。
# 都是实测扎过的口子:
#   awk 'BEGIN{system("rm -rf x")}'  —— awk/jq 能起子进程
#   find . -execdir rm {} +          —— -execdir 不是 -exec,别只写一个
#   git branch -D feature            —— 白名单里的 git 子命令也能删东西
#   sed -i / sort -o / tee           —— 动词只读,选项写文件
_MUTATES = re.compile(
    r"\bxargs\b|\bexec(?:dir)?\b|\beval\b|\bsource\b|\btee\b"
    r"|-delete\b|-fprintf?\b|-ok\b|-newer\w*\s|-execdir\b"
    r"|\bsed\s+[^|;&]*-i|\bsort\s+[^|;&]*-o\b"
    r"|\bsystem\s*\(|\bprint\s*>|\bENVIRON\b"          # awk 起子进程/写文件
    r"|\bgit\s+branch\s+[^|;&]*-[a-zA-Z]*[DdMm]\b"        # git branch -D/-d/-m
    r"|\bgit\s+\w+\s+[^|;&]*--(?:force|hard|prune)\b"
)

# 无害的重定向:丢弃输出、合并 stderr。先摘掉,剩下的 `>`/`<` 才是真写文件。
# 不摘的话 `ls 2>&1 | head` 会被误判 —— 实测模型很爱这么写。
_SAFE_REDIR = re.compile(r"2>&1|&>\s*/dev/null|2?>\s*/dev/null")

# 后台执行 `cmd &`:摘掉 `&&` 和安全重定向之后,还剩下的单个 `&` 就是它。
_BACKGROUND = re.compile(r"&")

# 分隔符。拆开后每一段都必须自己在白名单里。
_SEP = re.compile(r"&&|\|\||[;|]")


def is_ephemeral(cmd: str) -> bool:
    """这条 Bash 命令是不是"看一眼就完、结果会过期"的?

    **guard 和剪枝共用这一个判断** —— 主 agent 能自己跑的命令集合,必须等于
    结果会被标记过期的集合。见上面 EPHEMERAL_CMD 的注释。

    整条命令的**每一段**都得在白名单里。模型很自然会写
    ``git status && git branch -av && git log --oneline``,三段都只是看一眼;
    第一版一刀切拒绝所有复合命令,实测让 glance 完全失效 ——
    协调者三次尝试全被拦,只好回去派 subagent。
    但 ``git status && rm -rf x`` 必须拦住:前半段无害不代表整条无害。
    """
    if not cmd or not cmd.strip():
        return False
    if _SUBST.search(cmd) or _MUTATES.search(cmd):
        return False
    rest = _SAFE_REDIR.sub(" ", cmd)
    if ">" in rest or "<" in rest:
        return False           # 真正的重定向 —— 会写文件
    if _BACKGROUND.sub("", _SEP.sub(" ", rest)) != _SEP.sub(" ", rest):
        return False           # 摘掉 && / || 后还剩 & → 后台执行
    parts = [p.strip() for p in _SEP.split(rest)]
    return all(parts) and all(EPHEMERAL_CMD.match(p) for p in parts)


@dataclass
class EphemeralPolicy:
    """时效性清理 —— 和大小无关,和"还准不准"有关。

    只作用于 **Bash 工具**的结果,且命令匹配 :data:`EPHEMERAL_CMD`。
    读文件(Read)不在此列:文件内容不会因为时间流逝而失真到误导的程度,
    而且它可能是模型正在推理的依据。
    """

    enabled: bool = True

    keep_recent: int = 6
    """最近 N 条时效性结果保留原文。比 TrimPolicy 的 20 小得多 ——
    这类东西"最近"的窗口本来就短。"""

    max_chars: int = 2000
    """超过这个长度的交给 TrimPolicy 落盘归档,不走这条路 ——
    大输出里往往混着值得留档的东西。"""

    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"

    def placeholder(self, cmd: str, age: int) -> str:
        short = cmd.strip().splitlines()[0][:60]
        return self.text.format(cmd=f"`{short}`", age=age)


def _is_protected(entry: dict[str, Any]) -> bool:
    """压缩摘要 / 元信息不能动。"""
    return bool(entry.get("isCompactSummary") or entry.get("isMeta"))


def _content_text(content: Any) -> str | None:
    """只裁纯文本结果。图片/文档没有可读的文件形式,原样留着。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") in ("image", "document") for b in content):
            return None
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts) if parts else None
    return None


def _bash_commands(entries: list[dict[str, Any]]) -> dict[str, str]:
    """tool_use_id -> Bash 命令。tool_result 只带 id,命令在上一条 assistant 消息里。"""
    out: dict[str, str] = {}
    for e in entries:
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if (isinstance(b, dict) and b.get("type") == "tool_use"
                    and b.get("name") == "Bash" and b.get("id")):
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str):
                    out[b["id"]] = cmd
    return out


class TrimmingSessionStore(SqliteSessionStore):
    """append 全量落盘;load 时按策略裁剪后再喂回模型。"""

    def __init__(self, path: str | Path, workspace: str | Path,
                 policy: TrimPolicy | None = None,
                 ephemeral: EphemeralPolicy | None = None) -> None:
        super().__init__(path)
        self.workspace = Path(workspace).resolve()
        self.policy = policy or TrimPolicy()
        self.ephemeral = ephemeral if ephemeral is not None else EphemeralPolicy()
        self.last_report: dict[str, int] = {}

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        entries = await super().load(key)
        if entries is None:
            return entries
        self.last_report = {}      # 每次 load 重新计数
        if self.ephemeral.enabled:
            entries = self.expire(entries)
        if not self.policy.enabled:
            return entries
        return self.trim(entries)

    def expire(self, entries: list[SessionStoreEntry]) -> list[SessionStoreEntry]:
        """把过期的时效性 Bash 结果换成一句说明。块保留,只换正文。

        不落盘:一份过期的 ``git status`` 归档了也没人会去读,重跑一次就有。
        """
        ep = self.ephemeral
        cmds = _bash_commands(entries)

        sites: list[tuple[int, int, str]] = []   # (entry_idx, block_idx, cmd)
        for i, e in enumerate(entries):
            if _is_protected(e):
                continue
            content = (e.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for j, blk in enumerate(content):
                if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                    continue
                cmd = cmds.get(blk.get("tool_use_id"))
                if not cmd or not is_ephemeral(cmd):
                    continue
                text = _content_text(blk.get("content"))
                # 太大的交给 TrimPolicy 归档;已经被换过的(不是原始输出)不重复处理
                if text is None or len(text) > ep.max_chars:
                    continue
                sites.append((i, j, cmd))

        targets = sites[:-ep.keep_recent] if ep.keep_recent > 0 else sites
        if not targets:
            self.last_report |= {"expired": 0}
            return entries

        out = [dict(e) for e in entries]
        total = len(sites)
        for n, (i, j, cmd) in enumerate(targets):
            msg = dict(out[i]["message"])
            blocks = [dict(b) if isinstance(b, dict) else b for b in msg["content"]]
            blocks[j] = {**blocks[j], "content": ep.placeholder(cmd, total - n)}
            msg["content"] = blocks
            out[i] = {**out[i], "message": msg}
        self.last_report |= {"expired": len(targets)}
        return out

    def trim(self, entries: list[SessionStoreEntry]) -> list[SessionStoreEntry]:
        p = self.policy

        # 先定位所有可裁的 tool_result,按出现顺序;最后 keep_recent 个豁免。
        sites: list[tuple[int, int, str]] = []   # (entry_idx, block_idx, text)
        for i, e in enumerate(entries):
            if _is_protected(e):
                continue
            content = (e.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for j, blk in enumerate(content):
                if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                    continue
                text = _content_text(blk.get("content"))
                if text is not None and len(text) >= p.min_chars:
                    sites.append((i, j, text))

        targets = sites[:-p.keep_recent] if p.keep_recent > 0 else sites
        if not targets:
            # 用 |= 而不是 = :expire() 刚写进去的 "expired" 不能被冲掉。
            self.last_report |= {"cleared": 0, "kept": len(sites), "chars_saved": 0}
            return entries

        spill = self.workspace / p.spill_dirname
        spill.mkdir(parents=True, exist_ok=True)

        out = [dict(e) for e in entries]
        saved = 0
        for i, j, text in targets:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            f = spill / f"{digest}.txt"
            if not f.exists():
                f.write_text(text, encoding="utf-8")
            rel = f.relative_to(self.workspace)

            msg = dict(out[i]["message"])
            blocks = [dict(b) if isinstance(b, dict) else b for b in msg["content"]]
            blocks[j] = {**blocks[j], "content": p.placeholder(str(rel), len(text))}
            msg["content"] = blocks
            out[i] = {**out[i], "message": msg}
            saved += len(text)

        self.last_report |= {
            "cleared": len(targets),
            "kept": len(sites) - len(targets),
            "chars_saved": saved,
        }
        return out


def trim_report(store: TrimmingSessionStore) -> str:
    r = store.last_report
    if not r or not (r.get("cleared") or r.get("expired")):
        return "未裁剪"
    if not r.get("cleared"):
        return f"{r['expired']} 个时效性结果标记为过期"
    return (f"裁掉 {r['cleared']} 个工具结果(保留最近 {r['kept']} 个),"
            f"省下 ~{r['chars_saved'] // 4} tokens")
