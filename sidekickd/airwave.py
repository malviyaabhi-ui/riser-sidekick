"""HTTP client for the Airwave Sidekick API."""
from __future__ import annotations

import logging
from pathlib import Path

import aiohttp

from .config import Config, FIRMWARE
from .store import Store

log = logging.getLogger("airwave")


class Airwave:
    def __init__(self, cfg: Config, store: Store):
        self.cfg = cfg
        self.store = store

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.token}", "User-Agent": FIRMWARE}

    async def pair(self, code: str) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.post(f"{self.cfg.airwave_url}/api/sidekick/pair", json={"code": code, "firmware": FIRMWARE}) as r:
                data = await r.json(content_type=None)
                if r.status != 200:
                    raise RuntimeError(data.get("error", f"Pairing failed ({r.status})"))
        self.cfg.token = data["token"]
        self.cfg.device_id = data["device_id"]
        self.cfg.device_name = data.get("device_name") or self.cfg.device_name
        self.cfg.org_name = data.get("org_name", "")
        self.cfg.save()
        return data

    async def refresh_floors(self) -> int:
        """Download the floor list and cache plan images so the phone can load them offline."""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            async with s.get(f"{self.cfg.airwave_url}/api/sidekick/floors", headers=self._headers()) as r:
                data = await r.json(content_type=None)
                if r.status != 200:
                    raise RuntimeError(data.get("error", f"Floor list failed ({r.status})"))
            floors = data.get("floors", [])
            for f in floors:
                url = f.pop("plan_image_url", None)
                f["has_plan_image"] = False
                if not url:
                    continue
                try:
                    async with s.get(url) as img:
                        if img.status == 200:
                            path: Path = self.store.plan_path(f["id"])
                            path.write_bytes(await img.read())
                            f["has_plan_image"] = True
                            f["plan_content_type"] = img.headers.get("Content-Type", "image/png")
                except aiohttp.ClientError as e:
                    log.warning("plan image for %s: %s", f["id"], e)
        self.store.save_floors(floors, data.get("sites", []))
        return len(floors)

    async def sync(self) -> dict:
        sent = 0
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            while True:
                batch = self.store.unsynced(200)
                if not batch:
                    break
                async with s.post(f"{self.cfg.airwave_url}/api/sidekick/points", headers=self._headers(), json={"points": batch}) as r:
                    data = await r.json(content_type=None)
                    if r.status != 200:
                        raise RuntimeError(data.get("error", f"Upload failed ({r.status})"))
                self.store.mark_synced([p["id"] for p in batch])
                sent += len(batch)
        return {"sent": sent, **self.store.counts()}
