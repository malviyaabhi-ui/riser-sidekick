"""Passive WiFi scanning with `iw` on one or more USB radios.

Passive scans only: the MT7921 driver can reset when active probes are sent,
and listening is the right thing for a survey anyway.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger("scanner")

SUPPORTED_DRIVERS = {"mt7921u", "mt7925u", "mt76x2u", "rtw88_8822bu", "rtl8812au", "88XXau"}


@dataclass
class Reading:
    bssid: str
    ssid: str
    band: str          # "2.4" | "5" | "6"
    channel: int
    width_mhz: int
    rssi: float
    freq: int


def band_for_freq(freq: int) -> str | None:
    if 2400 <= freq <= 2500:
        return "2.4"
    if 5150 <= freq <= 5895:
        return "5"
    if 5925 <= freq <= 7125:
        return "6"
    return None


def channel_for_freq(freq: int) -> int:
    if freq == 2484:
        return 14
    if freq < 2484:
        return (freq - 2407) // 5
    if freq < 5925:
        return (freq - 5000) // 5
    return (freq - 5950) // 5  # 6 GHz: ch 1 = 5955


def find_radios() -> list[str]:
    """Interfaces whose driver is a known USB survey radio, excluding the Pi's built-in wlan0."""
    out = []
    for p in sorted(Path("/sys/class/net").glob("wl*")):
        drv = (p / "device" / "driver").resolve().name if (p / "device" / "driver").exists() else ""
        if drv in SUPPORTED_DRIVERS or (drv and "mt79" in drv):
            out.append(p.name)
    return out


async def _run(*cmd: str, timeout: float = 20) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, ""
    return proc.returncode or 0, out.decode(errors="replace")


async def prepare(iface: str, country: str) -> None:
    await _run("iw", "reg", "set", country)
    await _run("ip", "link", "set", iface, "up")


_BSS = re.compile(r"^BSS ([0-9a-f:]{17})", re.M)


def parse_scan(text: str) -> list[Reading]:
    readings: list[Reading] = []
    blocks = re.split(r"^BSS ", text, flags=re.M)[1:]
    for b in blocks:
        m = re.match(r"([0-9a-f:]{17})", b)
        if not m:
            continue
        bssid = m.group(1)
        freq_m = re.search(r"^\s*freq: (\d+)", b, re.M)
        sig_m = re.search(r"^\s*signal: (-?[\d.]+) dBm", b, re.M)
        ssid_m = re.search(r"^\s*SSID: (.*)$", b, re.M)
        if not (freq_m and sig_m):
            continue
        freq = int(freq_m.group(1))
        band = band_for_freq(freq)
        if not band:
            continue
        width = 20
        # HT operation: secondary channel present → 40 MHz (2.4 or 5 GHz)
        if re.search(r"^\s*\* secondary channel offset: (above|below)", b, re.M):
            width = 40
        # VHT operation (5 GHz): channel width 1 = 80/160, 2 = 160, 3 = 80+80
        vht = re.search(r"VHT operation:.*?\* channel width: (\d)", b, re.S)
        if vht and band != "2.4":
            width = {"1": 80, "2": 160, "3": 160}.get(vht.group(1), width)
            if vht.group(1) == "1" and re.search(r"center freq segment 2: [1-9]", b):
                width = 160
        # HE/EHT operation (6 GHz): channel width field in MHz
        he = re.search(r"(?:HE|EHT) operation:.*?\* channel width: (\d+)\s*MHz", b, re.S | re.I)
        if he and band == "6":
            width = int(he.group(1))
        if band == "2.4":
            width = min(width, 40)
        readings.append(Reading(
            bssid=bssid, ssid=(ssid_m.group(1).strip() if ssid_m else ""), band=band,
            channel=channel_for_freq(freq), width_mhz=width, rssi=float(sig_m.group(1)), freq=freq,
        ))
    return readings


async def scan_iface(iface: str, freqs: list[int] | None = None) -> list[Reading]:
    # iw grammar: scan [freq <f>*] ... [passive]  — "passive" must come last
    cmd = ["iw", "dev", iface, "scan"]
    if freqs:
        cmd += ["freq", *map(str, freqs)]
    cmd.append("passive")
    for attempt in range(3):
        rc, out = await _run(*cmd, timeout=40)
        if rc == 0:
            return parse_scan(out)
        if "Device or resource busy" in out or rc == 240:
            await asyncio.sleep(0.6 + attempt * 0.4)
            continue
        log.warning("scan on %s failed rc=%s: %s", iface, rc, out.strip()[:200])
        break
    return []


class Scanner:
    def __init__(self, interfaces: list[str] | None, country: str):
        self.country = country
        self._fixed = interfaces
        self._lock = asyncio.Lock()
        self._prepared: set[str] = set()

    @property
    def interfaces(self) -> list[str]:
        """Radios present right now; USB dongles can be plugged in after the service starts."""
        return self._fixed or find_radios()

    async def _prepare_all(self) -> None:
        for i in self.interfaces:
            if i not in self._prepared:
                await prepare(i, self.country)
                self._prepared.add(i)

    def plan(self) -> list[tuple[str, list[int] | None]]:
        """Split the bands across radios: first radio takes 5 GHz, second takes 2.4 + 6 GHz."""
        ifs = self.interfaces
        if len(ifs) >= 2:
            five = [5000 + 5 * c for c in (36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165)]
            two = [2412 + 5 * i for i in range(13)]                 # ch 1-13
            six = [5955 + 20 * i for i in range(59)]                # 6 GHz 20 MHz centres, ch 1-233
            return [(ifs[0], five), (ifs[1], two + six)]
        return [(i, None) for i in ifs]

    async def scan(self) -> list[dict]:
        """One survey scan: all radios in parallel, strongest reading per BSSID."""
        async with self._lock:
            await self._prepare_all()
            results = await asyncio.gather(*(scan_iface(i, f) for i, f in self.plan()))
        best: dict[str, Reading] = {}
        for rs in results:
            for r in rs:
                if r.bssid not in best or r.rssi > best[r.bssid].rssi:
                    best[r.bssid] = r
        return [asdict(r) for r in sorted(best.values(), key=lambda r: -r.rssi)]
