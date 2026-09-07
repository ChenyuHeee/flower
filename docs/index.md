# flower

**基于 [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) 的可移植长程 agent 框架。**

不牺牲 Claude Code 的能力,把它变成一个能带走、能定制交互、能跑几天的专用 agent。

---

## 装

```bash
curl -fsSL https://raw.githubusercontent.com/ChenyuHeee/flower/main/install.sh | sh
```

自动找 `uv` / `pipx` / `pip` 装好 `flower` 命令。然后进任意项目目录:

```bash
cd ~/我的项目
flower
```

第一次会问你要 API key / 网关地址,配一次存到 `~/.config/flower/.env`,处处生效。
**本机已经装了 Claude Code 并配好的话,flower 直接借它的 token,连问都不问。**

!!! tip "它是 Python 工具,不是 npm"
    命令名叫 `flower`,但底层是 pip 包。装完 `flower` 就是个全局命令,和 `git` 一样在哪都能用。

## 它替你挡四类失败

| 你怕的事 | flower 的机制 |
|---|---|
| **做出来不是想要的** | [前置确认](clarify.md):动手前先把需求问清、冻结成文书 |
| **说做完了其实没做完** | [目标看守](goal.md):独立角色每轮判定,没达成打回去接着做 |
| **跑几小时崩了从头再来** | [接续](continuity.md):同一目录再跑就接上上次,进程被杀也一样 |
| **上下文满了被压成一段摘要** | [换代](handoff.md):写一份可读可改的交接,换新会话接手,不 compact |

## 它凭什么"长程"

主 agent 只装决策,不动手 —— 写码、跑测试、查资料全派给 subagent,
subagent 的试错进的是**另一条** transcript,主线程只收报告。
实测一次重活 **94.8% 的内容沉在 subagent 里**,主线程上下文才涨得慢。
细节和实测数据见 [快速上手](start.md) 和两个真实案例。

## 真的跑过

- **[HT001](case-ht001.md)** —— 从零写一个终端 IDE。$171.62 / 10.4 小时 / 主线程上下文涨到 185.9K。
- **[HT002](case-ht002.md)** —— 把它装到 macOS 上跑起来。$38.24 / 1 小时,首次带目标看守。

两个案例的每个数字都能在 `runs/manifest.json`、`sessions.db` 里复算 —— 这是原始记录,不是宣传。

---

<div style="text-align:center; opacity:0.7">
<a href="https://github.com/ChenyuHeee/flower">GitHub</a> ·
基于 Claude Agent SDK · MIT
</div>
