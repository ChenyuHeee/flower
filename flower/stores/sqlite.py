"""SQLite SessionStore —— 长程运行的持久化地基。

SDK 默认把 transcript 落在宿主机文件系统上;长程 workflow 需要的是可查询、可迁移、
可跨进程 resume 的存储。这里用 SQLite 做零外部依赖的实现。

要换 Postgres / S3 / Redis:实现同一个协议即可,SDK 自带一致性测试套件
`claude_agent_sdk.testing.session_store_conformance` 可以直接验证你的实现。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from claude_agent_sdk import (
    SessionKey,
    SessionListSubkeysKey,
    SessionStore,
    SessionStoreEntry,
    SessionStoreListEntry,
    SessionSummaryEntry,
    fold_session_summary,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
-- uuid 是幂等键:失败批次会被重试 3 次,重放不能产生重复行,
-- 否则 resume 出来的 transcript 是坏的。没有 uuid 的条目(标题/标签/模式标记)不去重。
CREATE UNIQUE INDEX IF NOT EXISTS entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE IF NOT EXISTS meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
"""


def _skey(key: SessionKey) -> str:
    parts = [key["project_key"], key["session_id"]]
    if sub := key.get("subpath"):
        parts.append(sub)
    return "/".join(parts)


class SqliteSessionStore(SessionStore):
    """把 transcript 镜像进 SQLite。子 agent 的 transcript 用 subpath 区分。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self._last_mtime = 0

    def _next_mtime(self) -> int:
        # 必须严格单调:list_sessions 与 summary sidecar 共用这个时钟,
        # 否则 SDK 的 staleness 快路径会误判。
        now = int(time.time() * 1000)
        if now <= self._last_mtime:
            now = self._last_mtime + 1
        self._last_mtime = now
        return now

    # --- SessionStore 协议 -------------------------------------------------

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        k = _skey(key)
        now = self._next_mtime()
        cur = self._db.cursor()
        row = cur.execute("SELECT next_seq FROM meta WHERE store_key=?", (k,)).fetchone()
        seq = row[0] if row else 0

        # 按 uuid 去重:先去掉已落库的,再去掉批次内自身重复的。
        uids = [e.get("uuid") for e in entries]
        known = {
            r[0]
            for r in cur.execute(
                "SELECT uid FROM entries WHERE store_key=? AND uid IN (%s)"
                % ",".join("?" * len(uids or [None])),
                (k, *uids),
            )
        } if uids else set()
        fresh: list[tuple[str, int, str | None, str]] = []
        seen: set[str] = set()
        new_entries: list[SessionStoreEntry] = []
        for e in entries:
            uid = e.get("uuid")
            if uid is not None and (uid in known or uid in seen):
                continue
            if uid is not None:
                seen.add(uid)
            fresh.append((k, seq + len(fresh), uid, json.dumps(e)))
            new_entries.append(e)
        if not new_entries:
            return  # 整批都是重放,不推进 mtime,也不重复 fold summary

        cur.executemany(
            "INSERT INTO entries(store_key, seq, uid, payload) VALUES (?,?,?,?)", fresh
        )
        cur.execute(
            "INSERT INTO meta(store_key, mtime, next_seq) VALUES (?,?,?) "
            "ON CONFLICT(store_key) DO UPDATE SET mtime=excluded.mtime, next_seq=excluded.next_seq",
            (k, now, seq + len(fresh)),
        )
        # 主 transcript 才参与 summary;子 agent 的不算。
        if key.get("subpath") is None:
            pk, sid = key["project_key"], key["session_id"]
            prev_row = cur.execute(
                "SELECT data FROM summaries WHERE project_key=? AND session_id=?", (pk, sid)
            ).fetchone()
            prev = json.loads(prev_row[0]) if prev_row else None
            folded = fold_session_summary(prev, key, new_entries)
            folded["mtime"] = now  # 存储写入时刻,不是 entry 时间戳
            cur.execute(
                "INSERT INTO summaries(project_key, session_id, mtime, data) VALUES (?,?,?,?) "
                "ON CONFLICT(project_key, session_id) DO UPDATE SET mtime=excluded.mtime, data=excluded.data",
                (pk, sid, now, json.dumps(folded)),
            )
        self._db.commit()

    def projects(self) -> list[str]:
        """库里实际存在的 project_key。SDK 由 cwd 推导它,不由调用方指定 ——
        所以查询前用这个确认,别猜。"""
        return sorted({k.split("/", 1)[0] for (k,) in self._db.execute("SELECT store_key FROM meta")})

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        rows = self._db.execute(
            "SELECT payload FROM entries WHERE store_key=? ORDER BY seq", (_skey(key),)
        ).fetchall()
        return [json.loads(r[0]) for r in rows] if rows else None

    async def list_sessions(self, project_key: str) -> list[SessionStoreListEntry]:
        prefix = project_key + "/"
        out: list[SessionStoreListEntry] = []
        for k, mtime in self._db.execute("SELECT store_key, mtime FROM meta"):
            if k.startswith(prefix):
                rest = k[len(prefix):]
                if "/" not in rest:  # 只要主 transcript
                    out.append({"session_id": rest, "mtime": mtime})
        return out

    async def list_session_summaries(self, project_key: str) -> list[SessionSummaryEntry]:
        rows = self._db.execute(
            "SELECT data FROM summaries WHERE project_key=?", (project_key,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    async def delete(self, key: SessionKey) -> None:
        k = _skey(key)
        cur = self._db.cursor()
        cur.execute("DELETE FROM entries WHERE store_key=?", (k,))
        cur.execute("DELETE FROM meta WHERE store_key=?", (k,))
        if key.get("subpath") is None:
            # 删主 transcript 级联删掉子 agent 的,避免孤儿
            pk, sid = key["project_key"], key["session_id"]
            cur.execute("DELETE FROM summaries WHERE project_key=? AND session_id=?", (pk, sid))
            like = f"{pk}/{sid}/%"
            cur.execute("DELETE FROM entries WHERE store_key LIKE ?", (like,))
            cur.execute("DELETE FROM meta WHERE store_key LIKE ?", (like,))
        self._db.commit()

    async def list_subkeys(self, key: SessionListSubkeysKey) -> list[str]:
        prefix = f"{key['project_key']}/{key['session_id']}/"
        return [
            k[len(prefix):]
            for (k,) in self._db.execute("SELECT store_key FROM meta")
            if k.startswith(prefix)
        ]

    def close(self) -> None:
        self._db.close()
