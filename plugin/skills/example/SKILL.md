---
name: example
description: 占位示例。当用户要求"验证 flower 插件链路"时使用,用来确认领域能力包被正确加载。
---

# 示例技能

这是一个占位 skill,唯一作用是证明 `plugin/` 目录被 SDK 正确加载了。

被调用时,输出一行:`flower 插件链路正常`,然后停止。

真正的领域能力放在这里:
- `plugin/skills/<名字>/SKILL.md` —— 需要时才加载的领域知识(概率性:模型判断相关才用)
- `plugin/agents/<名字>.md` —— 子 agent,独立上下文窗口
- `plugin/hooks/hooks.json` —— 确定性拦截(必然执行,不依赖模型判断)
- `plugin/.mcp.json` —— 外部工具接入
