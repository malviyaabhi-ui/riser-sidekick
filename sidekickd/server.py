"""Survey web app served by the Sidekick on port 80 (hotspot) and riser-sidekick.local."""
from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import uuid
from pathlib import Path

from aiohttp import web

from .airwave import Airwave
from .config import Config, DATA_DIR, FIRMWARE
from .scanner import Scanner
from .store import Store

log = logging.getLogger("server")
STATIC = Path(__file__).parent / "static"


def online() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=1.5).close()
        return True
    except OSError:
        return False


def make_app() -> web.Application:
    cfg = Config.load()
    store = Store(DATA_DIR)
    scanner = Scanner(cfg.scan_interfaces or None, cfg.country)
    airwave = Airwave(cfg, store)
    app = web.Application(client_max_size=4 * 1024 * 1024)
    routes = web.RouteTableDef()

    @routes.get("/")
    async def index(_req):
        return web.FileResponse(STATIC / "index.html")

    @routes.get("/api/status")
    async def status(_req):
        return web.json_response({
            "firmware": FIRMWARE, "paired": cfg.paired, "device_name": cfg.device_name, "org_name": cfg.org_name,
            "airwave_url": cfg.airwave_url, "radios": scanner.interfaces, "online": online(),
            "hotspot_ssid": cfg.hotspot_ssid, **store.counts(),
        })

    @routes.post("/api/pair")
    async def pair(req):
        body = await req.json()
        try:
            data = await airwave.pair(str(body.get("code", "")).strip())
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": str(e)}, status=400)
        try:
            await airwave.refresh_floors()
        except Exception as e:  # noqa: BLE001
            log.warning("floors after pairing: %s", e)
        return web.json_response({"ok": True, "org_name": data.get("org_name", ""), "device_name": cfg.device_name})

    @routes.post("/api/refresh")
    async def refresh(_req):
        if not cfg.paired:
            return web.json_response({"error": "Pair the device first"}, status=400)
        try:
            n = await airwave.refresh_floors()
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": f"Could not reach Airwave: {e}"}, status=502)
        return web.json_response({"floors": n})

    @routes.get("/api/floors")
    async def floors(_req):
        fl, sites = store.floors()
        return web.json_response({"floors": fl, "sites": sites})

    @routes.get("/api/floors/{id}/plan")
    async def plan_image(req):
        p = store.plan_path(req.match_info["id"])
        if not p.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(p, headers={"Cache-Control": "max-age=3600"})

    @routes.get("/api/floors/{id}/points")
    async def floor_points(req):
        return web.json_response({"points": store.points_for_floor(req.match_info["id"])})

    @routes.post("/api/scan")
    async def scan(_req):
        return web.json_response({"readings": await scanner.scan()})

    @routes.post("/api/points")
    async def add_point(req):
        body = await req.json()
        try:
            floor_id, session_id = str(body["floor_id"]), str(body.get("session_id") or uuid.uuid4())
            x, y = float(body["x"]), float(body["y"])
        except (KeyError, ValueError):
            return web.json_response({"error": "floor_id, x and y are required"}, status=400)
        readings = await scanner.scan()
        point = store.add_point(floor_id, session_id, x, y, readings)
        return web.json_response(point)

    @routes.delete("/api/points/{id}")
    async def delete_point(req):
        store.delete_point(req.match_info["id"])
        return web.json_response({"ok": True})

    @routes.post("/api/sync")
    async def sync(_req):
        if not cfg.paired:
            return web.json_response({"error": "Pair the device first"}, status=400)
        try:
            return web.json_response(await airwave.sync())
        except Exception as e:  # noqa: BLE001
            return web.json_response({"error": f"Sync failed: {e}", **store.counts()}, status=502)

    @routes.post("/api/network")
    async def network(req):
        """Switch the built-in radio between hotspot (survey) and client (sync) modes."""
        body = await req.json()
        mode = body.get("mode")
        if mode == "hotspot":
            cmd = ["nmcli", "dev", "wifi", "hotspot", "ifname", "wlan0", "ssid", cfg.hotspot_ssid, "password", cfg.hotspot_password]
        elif mode == "client" and body.get("ssid"):
            cmd = ["nmcli", "dev", "wifi", "connect", str(body["ssid"]), "password", str(body.get("password", "")), "ifname", "wlan0"]
        else:
            return web.json_response({"error": "mode must be hotspot or client (with ssid)"}, status=400)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired) as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"ok": out.returncode == 0, "output": (out.stdout + out.stderr).strip()[-400:]})

    app.add_routes(routes)
    app.router.add_static("/static", STATIC)

    async def background_sync(app_):
        """Upload pending points whenever the box is online."""
        async def loop():
            while True:
                await asyncio.sleep(30)
                if cfg.paired and store.counts()["pending"] and online():
                    try:
                        await airwave.sync()
                    except Exception as e:  # noqa: BLE001
                        log.info("background sync: %s", e)
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app.cleanup_ctx.append(background_sync)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    web.run_app(make_app(), host="0.0.0.0", port=80, access_log=None)


if __name__ == "__main__":
    main()
