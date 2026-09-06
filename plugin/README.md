# 领域能力包

这个目录是 flower 的"可移植"边界。框架代码不含任何领域知识,
领域知识全部在这里,随仓库一起走。

SDK 侧由 `flower/core/agent.py` 的 `plugins=[{"type":"local","path":PLUGIN_DIR}]` 挂载,
且 `setting_sources=[]` —— 宿主机的 `~/.claude/` 与项目 `.claude/` 一律不读。
所以换一台机器,行为完全一致。

| 目录 | 作用 | 触发方式 |
|---|---|---|
| `skills/<name>/SKILL.md` | 领域知识,按需加载 | 概率性 —— 模型判断相关才用 |
| `agents/<name>.md` | 子 agent,独立上下文 | 模型委派,或 workflow 里显式指定 |
| `hooks/hooks.json` | 拦截工具调用 | 确定性 —— 匹配即执行 |
| `.mcp.json` | 外部工具 | 注册为工具,同内置工具 |
