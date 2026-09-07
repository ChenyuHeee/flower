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


# 探针结论。**只有 "auth"/"config" 才该去重配** —— 网络不通时让人重配一个
# 本来好好的 token 是帮倒忙,判不准时也一律放行(探针不该成为新的故障点)。
PROBE_OK, PROBE_AUTH, PROBE_CONFIG, PROBE_NET = "ok", "auth", "config", "net"


PROBE_MAX_TOKENS = 16
"""探针的 max_tokens。**别设成 1** —— 实测那样反而更慢:强制思维链的模型
连思考都放不下,服务端一路挣扎到 30 秒才返回;设 16 只要 3.6 秒。
"越省越慢",这里省的那点钱不值得拿超时去换。"""


def probe_credentials(timeout: float = 20.0) -> tuple[str, str]:
    """真的打一次 API,确认这套凭证能用。返回 ``(结论, 说明)``。

    为什么要探:``check_credentials`` 只看环境变量**存在没有**,
    过期/写错/网关地址不对的 token 照样过关,然后跑到几分钟后才炸。
    开跑前花一秒钟问一句,比让人白等强。

    用 ``max_tokens=16`` 的最小请求(见 :data:`PROBE_MAX_TOKENS`),几乎不花钱。
    走 stdlib,不引依赖。

    **失败要分类**:
      * ``auth``   —— 401/403/密钥无效 → 该重配
      * ``config`` —— 404/模型不存在 → 网关地址或模型名不对,也该重配
      * ``net``    —— 连不上/超时/5xx → **网络问题,不是凭证问题**,别让人瞎重配
      * ``ok``     —— 通了;判不准的一律当 ok 放行(宁可跑起来再说)
    """
    import json as _json
    import urllib.error
    import urllib.request

    key = os.environ.get("ANTHROPIC_API_KEY")
    tok = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not (key or tok):
        return PROBE_AUTH, "没有凭证"

    base = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
    model = (os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
             or os.environ.get("ANTHROPIC_MODEL") or "claude-3-5-haiku-20241022")
    body = _json.dumps({"model": model, "max_tokens": PROBE_MAX_TOKENS,
                        "messages": [{"role": "user", "content": "hi"}]}).encode()
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if key:
        headers["x-api-key"] = key
    else:
        headers["authorization"] = f"Bearer {tok}"

    req = urllib.request.Request(f"{base}/v1/messages", data=body,
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (PROBE_OK, "") if r.status < 400 else (PROBE_NET, f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:                       # noqa: BLE001
            pass
        if e.code in (401, 403):
            return PROBE_AUTH, f"HTTP {e.code} 认证被拒 {detail}"
        low = detail.lower()
        # **判据要严**:Anthropic 风格的错误 JSON 里几乎必然出现 "model" 这个词,
        # 拿它当"模型名不对"会把瞬时 400 误判成配置错误,然后逼人重配。
        # 必须明说"找不到/不存在"才算。
        model_gone = any(k in low for k in
                         ("not_found", "not found", "does not exist", "unknown model",
                          "no such model", "invalid model"))
        if e.code == 404 or (e.code == 400 and model_gone):
            return PROBE_CONFIG, f"HTTP {e.code} 网关地址或模型名不对 {detail}"
        if e.code >= 500:
            return PROBE_NET, f"HTTP {e.code} 服务端错误(不是你的凭证)"
        return PROBE_OK, f"HTTP {e.code}(判不准,放行){detail[:80]}"
    except Exception as e:                      # noqa: BLE001 —— 连不上/超时/DNS/TLS
        return PROBE_NET, f"{type(e).__name__}: {e}"


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
