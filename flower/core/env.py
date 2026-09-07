"""凭证与端点 —— 可移植的另一半。

`setting_sources=[]` 让 flower 不读宿主机的 `~/.claude/settings.json`。
好处是行为一致,代价是那里面的 `env` 块(BASE_URL、TOKEN、模型映射)也一并不读了。
所以凭证必须由 flower 自己带。查找顺序(先找到的先赢,进程环境永远最高):

    1. 进程环境变量
    2. 当前目录的 `.env`        —— cd 到哪个项目就近读哪个
    3. `~/.config/flower/.env`  —— 装一次、处处生效(pip/pipx/uv 安装后放这)
    4. 源码仓库根的 `.env`       —— 从源码跑时(开发)
    5. `~/.claude/settings.json` 的 env 块 —— **回退**:本机装了 Claude Code 就借它的 token

第 3 条是**分发的关键**:pip 装出来的 flower 在 site-packages 里,没有"仓库根",
朋友没地方放 `.env`。`~/.config/flower/.env` 给了每人一个固定的全局位置。
`flower setup` 会把 token 写到那里。

第 5 条是**分发的便利**:本机已经装了 Claude Code 并登录/配好的人,连 setup 都不用跑。
注意这**不违背** `setting_sources=[]` 的可移植性承诺 —— 我们只取那几个凭证键
(KNOWN),不让 settings.json 的其它任何东西影响 agent 行为。借的是"去哪找 token"。
"""

from __future__ import annotations

import json
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


def user_env_path() -> Path:
    """每人全局的凭证文件位置。`flower setup` 写它,`load_dotenv` 读它。"""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "flower" / ".env"


def _env_candidates() -> list[Path]:
    """按优先级从高到低找 `.env`。先找到的键先赢(进程环境更高,在解析里保证)。"""
    out: list[Path] = []
    if env := os.environ.get("FLOWER_ENV"):
        out.append(Path(env))                                    # 显式指定,最高
    out.append(Path.cwd() / ".env")                              # 项目本地
    out.append(user_env_path())                                 # 每人全局
    out.append(Path(__file__).resolve().parent.parent.parent / ".env")  # 源码根
    return out


def _claude_code_env() -> dict[str, str]:
    """Claude Code 的 `~/.claude/settings.json` 里 env 块的凭证 —— **最后的回退**。

    本机已经装了 Claude Code 并配好的人,flower 直接借它的 token,连 setup 都免了。
    **只取 KNOWN 里那几个凭证键**,不接管 settings.json 的其它任何东西 ——
    这和 `setting_sources=[]` 的可移植性承诺不冲突(借的是"去哪找 token")。
    读不动就返回空:回退失效不该带走这次运行。
    """
    out: dict[str, str] = {}
    for name in ("settings.json", "settings.local.json"):
        try:
            data = json.loads((Path.home() / ".claude" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        env = data.get("env") if isinstance(data, dict) else None
        if isinstance(env, dict):
            for k in KNOWN:
                if k in env and k not in out and env[k]:
                    out[k] = str(env[k])
    return out


def load_dotenv(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """极简 .env 解析。已存在的环境变量默认不覆盖(进程环境优先)。

    不传 ``path`` 就按 :func:`_env_candidates` 的顺序把**所有存在的**文件依次读入,
    最后再拿 Claude Code 的 env 块兜底 —— 靠"已设的键不覆盖"实现优先级:
    排在前面的先把键占住,后面的补空缺。所以当前目录的 `.env` 盖过
    `~/.config/flower/.env`,两者又都盖过 `~/.claude` 的回退,而全都盖不过进程环境。
    """
    auto = path is None
    paths = _env_candidates() if auto else [Path(path)]
    loaded: dict[str, str] = {}

    def take(k: str, v: str) -> None:
        if override or k not in os.environ:
            os.environ[k] = v
            loaded[k] = v

    for p in paths:
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            take(k.strip(), v.strip().strip("'\""))

    if auto:                                  # Claude Code 回退只在自动查找时用
        for k, v in _claude_code_env().items():
            take(k, v)
    return loaded


def check_credentials() -> str | None:
    """返回错误说明,或 None 表示可用。"""
    if not any(os.environ.get(k) for k in REQUIRED_ANY):
        return (
            "缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。\n"
            "最省事:跑一次 `flower setup`,把 token 存到 "
            f"{user_env_path()}(装一次,处处生效)。\n"
            "或者:在当前目录建 `.env`,或 export 进进程环境。\n"
            "flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。"
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
