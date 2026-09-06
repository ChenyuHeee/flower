"""凭证与端点 —— 可移植的另一半。

`setting_sources=[]` 让 flower 不读宿主机的 `~/.claude/settings.json`。
好处是行为一致,代价是那里面的 `env` 块(BASE_URL、TOKEN、模型映射)也一并不读了。
所以凭证必须由 flower 自己带:进程环境 > 仓库根的 `.env`。

`.env` 已在 .gitignore 里 —— 换机器时单独拷,不进版本库。
"""

from __future__ import annotations

import os
from pathlib import Path

REQUIRED_ANY = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# 这些是 flower 关心的;其余 .env 行照样加载,不做白名单限制。
KNOWN = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_EFFORT_LEVEL",
)


def load_dotenv(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """极简 .env 解析。已存在的环境变量默认不覆盖(进程环境优先)。"""
    p = Path(path) if path else Path(__file__).resolve().parent.parent.parent / ".env"
    loaded: dict[str, str] = {}
    if not p.is_file():
        return loaded
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if override or k not in os.environ:
            os.environ[k] = v
            loaded[k] = v
    return loaded


def check_credentials() -> str | None:
    """返回错误说明,或 None 表示可用。"""
    if not any(os.environ.get(k) for k in REQUIRED_ANY):
        return (
            "缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。\n"
            "flower 不读 ~/.claude/settings.json(那是可移植性的代价),\n"
            "请设进程环境,或写进仓库根的 .env(见 .env.example)。"
        )
    return None


def describe() -> dict[str, str]:
    """当前生效的配置,token 打码。用于启动时打印一行,确认没连错端点。

    打码只留前 4 位:够分辨"是不是用错了那把 key",又不至于在截图、粘贴日志、
    贴给别人看的时候漏掉有意义的一段。短 token(网关签发的常常只有十几位)
    留 7 位就已经泄掉三分之一了。
    """
    out = {}
    for k in KNOWN:
        v = os.environ.get(k)
        if not v:
            continue
        out[k] = (f"{v[:4]}***(共 {len(v)} 位)") if ("TOKEN" in k or "KEY" in k) else v
    out.setdefault("ANTHROPIC_BASE_URL", "https://api.anthropic.com (默认)")
    return out
