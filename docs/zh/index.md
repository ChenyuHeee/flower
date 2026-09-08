# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">基于 Claude Agent SDK 的可移植长程 agent 框架。</p>

<p class="fl-hero__sub">不牺牲 Claude Code 的能力,把它变成一个能带走、能定制交互、能跑几天的专用 agent。
主线程上那个 agent 只做决策,动手的活全派给 subagent;需求先问清楚再开工,做完没做完由另一个角色判。
换一台机器行为一致 —— 它不读宿主机的设置,凭证自己带。</p>

[快速上手](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>一次运行的花费</span></div>
<div class="fl-stat"><b>10.4 小时</b><span>连续跑,中途断网自己接上</span></div>
<div class="fl-stat"><b>185.9K</b><span>主线程上下文峰值,全程没压缩</span></div>
<div class="fl-stat"><b>94.8%</b><span>正文字符落在 subagent</span></div>
</div>

四个数字出自 [HT001](cases/ht001.md) —— 一个 agent 在 flower 下从零写出一个终端 IDE 的那次运行。

## 一条命令装好,不用 Node {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

脚本自动找 `uv` / `pipx` / `pip` 把 `flower` 命令装上,只要 Python ≥ 3.10,
Claude Code CLI 也不用装。装完 `cd` 到任意项目目录敲一句 `flower`:第一次会问你要 API key
或网关地址,配一次存到 `~/.config/flower/.env`,处处生效;本机已经装了 Claude Code 并配好的话,
它直接借那份 token,连问都不问。完整步骤和排错见[安装](getting-started/install.md)。

## 它替你挡四类失败 {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [前置确认](guide/clarify.md) {#前置确认}

怕做出来不是想要的 —— 动手之前有一个只提问、不动手的角色问到清楚为止,把需求冻结成一份文书,
后面每一步读它开局。
</div>

<div class="fl-card" markdown>
### [目标看守](guide/goal.md) {#目标看守}

怕它说做完了其实没做完 —— 每一轮活结束由另一个角色独立判一次,达成往下走,没达成打回去,
这个环境验不了就停下来问人。
</div>

<div class="fl-card" markdown>
### [接续](guide/continuity.md) {#接续}

怕跑几小时崩了从头再来 —— 在同一个目录再敲一次 `flower` 就接上上次的进度,进程被 kill、
机器重启也一样,你不用记任何 id。
</div>

<div class="fl-card" markdown>
### [换代](guide/handoff.md) {#换代}

怕上下文满了被压成一段摘要 —— 当前会话自己写一份人能读、能改的交接书,换一条新会话接手,
不用 compact。
</div>

</div>

## 它凭什么"长程" {#长程}

主线程上的[协调者](reference/glossary.md#协调者)只装决策,拿不到 `Write` 和 `Edit` ——
写码、跑测试、查资料全派给 [subagent](reference/glossary.md#subagent),
subagent 的试错进的是**另一条** transcript,主线程只收一份不超过 30 行的报告。
HT001 那次 10.4 小时的运行里,**94.8% 的正文字符落在 subagent**,
1,893 次动手的工具调用只有 32 次进了协调者的视野。
所以主线程 70 轮才涨到 185.9K、全程没有发生过压缩 —— 这一层怎么做的、另外三层是什么,
见[上下文经济学](guide/context.md)。

## 两次真实长跑的原始记录 {#真的跑过}

- **[HT001](cases/ht001.md)** —— 从零写一个终端 IDE。$171.62 / 10.4 小时 /
  主线程上下文涨到 185.9K,交出 12,212 行产品代码,中途断过一次网、自己接着跑完。
- **[HT002](cases/ht002.md)** —— 把它装到 macOS 上跑起来。$38.24 / 约 1 小时,首次带目标看守;
  程序确实跑起来了,而判定结论是**无法达成**,浮上来问人。

两页都写了站不住的地方:HT001 里 agent 给自己的验收判错了一条,
HT002 把 `git clone && make && ./cppide` 做成了一小时。每个数字都能在 `runs/manifest.json`
和 `sessions.db` 里复算 —— 是记录,不是宣传。

## 从哪读起 {#从哪读起}

- **想马上跑起来** —— [快速上手](getting-started/quickstart.md):三条命令跑起来,
  然后教你读屏幕上滚过去的东西。
- **想先搞懂概念** —— [核心概念](getting-started/concepts.md):运行、步骤、会话、五个角色,
  五分钟一次说完。
- **想接进自己的代码** —— [Python API](reference/api.md):`Runtime`、`Step`、五个角色工厂,
  62 个公开符号的签名和默认值。
