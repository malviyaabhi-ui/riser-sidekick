"""Local SQLite store for survey points and cached floors, plus sync to Airwave."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path

log = logging.getLogger("store")


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir = data_dir / "plans"
        self.plans_dir.mkdir(exist_ok=True)
        self.db = sqlite3.connect(data_dir / "sidekick.db", check_same_thread=False)
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(
            """
            create table if not exists points (
              id text primary key, floor_id text not null, session_id text not null,
              x real not null, y real not null, captured_at text not null,
              readings text not null, synced integer not null default 0
            );
            create index if not exists points_floor on points(floor_id, synced);
            create table if not exists floors (id text primary key, json text not null, fetched_at real not null);
            create table if not exists kv (k text primary key, v text not null);
            """
        )

    # ---- points -------------------------------------------------------
    def add_point(self, floor_id: str, session_id: str, x: float, y: float, readings: list[dict]) -> dict:
        pid = str(uuid.uuid4())
        captured = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.db.execute(
            "insert into points (id, floor_id, session_id, x, y, captured_at, readings) values (?,?,?,?,?,?,?)",
            (pid, floor_id, session_id, x, y, captured, json.dumps(readings)),
        )
        self.db.commit()
        return {"id": pid, "floor_id": floor_id, "session_id": session_id, "x": x, "y": y, "captured_at": captured, "readings": readings, "synced": False}

    def delete_point(self, pid: str) -> None:
        self.db.execute("delete from points where id = ?", (pid,))
        self.db.commit()

    def points_for_floor(self, floor_id: str) -> list[dict]:
        rows = self.db.execute("select id, session_id, x, y, captured_at, readings, synced from points where floor_id = ? order by captured_at", (floor_id,)).fetchall()
        return [{"id": r[0], "session_id": r[1], "x": r[2], "y": r[3], "captured_at": r[4], "readings": json.loads(r[5]), "synced": bool(r[6])} for r in rows]

    def unsynced(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute("select id, floor_id, session_id, x, y, captured_at, readings from points where synced = 0 limit ?", (limit,)).fetchall()
        return [{"id": r[0], "floor_id": r[1], "session_id": r[2], "x": r[3], "y": r[4], "captured_at": r[5], "readings": json.loads(r[6])} for r in rows]

    def mark_synced(self, ids: list[str]) -> None:
        self.db.executemany("update points set synced = 1 where id = ?", [(i,) for i in ids])
        self.db.commit()

    def counts(self) -> dict:
        total, pending = self.db.execute("select count(*), sum(case when synced=0 then 1 else 0 end) from points").fetchone()
        return {"total": total or 0, "pending": pending or 0}

    # ---- floors ---------------------------------------------------------
    def save_floors(self, floors: list[dict], sites: list[dict]) -> None:
        now = time.time()
        self.db.execute("delete from floors")
        self.db.executemany("insert into floors (id, json, fetched_at) values (?,?,?)", [(f["id"], json.dumps(f), now) for f in floors])
        self.db.execute("insert or replace into kv (k, v) values ('sites', ?)", (json.dumps(sites),))
        self.db.commit()

    def floors(self) -> tuple[list[dict], list[dict]]:
        floors = [json.loads(r[0]) for r in self.db.execute("select json from floors").fetchall()]
        row = self.db.execute("select v from kv where k = 'sites'").fetchone()
        return floors, (json.loads(row[0]) if row else [])

    def plan_path(self, floor_id: str) -> Path:
        return self.plans_dir / f"{floor_id}.img"
