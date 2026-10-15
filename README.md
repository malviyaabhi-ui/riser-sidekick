# Riser Sidekick

Walk-survey box for [Riser Airwave](https://github.com/malviyaabhi-ui/riser-airwave). A Raspberry Pi 5 with two USB WiFi 6E radios scans passively on 2.4, 5 and 6 GHz, serves a survey page to any phone over its own hotspot, stores readings locally, and syncs them to Airwave where they appear as the **Measured** layer next to the predicted heatmap.

The phone is only a screen, so iPhone WiFi-scanning limits do not apply.

## Hardware (lab kit)

- Raspberry Pi 5, 8 GB, with a fan case and a 27 W USB-C supply (5 V 5 A, needed to power two radios)
- 2 × MediaTek MT7921AU WiFi 6E USB adapters (BrosTrend AX9L / AXE3000, ALFA AWUS036AXM, EDUP EP-AX1672, Panda PAU0F)
- Short USB 3.0 extension cables so the radios sit apart from the Pi
- 64 GB microSD card (A1)
- Optional later: tinySA Ultra spectrum analyser, USB-C power bank

## Flash and install

1. **Raspberry Pi Imager** → Raspberry Pi 5 → **Raspberry Pi OS Lite (64-bit)** → your card.
   In the settings step: hostname `riser-sidekick`, username `riser` with a password, enable SSH, set WiFi to your office network (used only for the first install), locale Asia/Dubai.
2. Boot the Pi on Ethernet or the office WiFi, then from a laptop:
   ```bash
   ssh riser@riser-sidekick.local
   sudo apt-get install -y git
   git clone https://github.com/malviyaabhi-ui/riser-sidekick.git
   cd riser-sidekick && sudo bash install.sh
   ```
   The installer prints the hotspot name and password at the end.
3. Plug in both radios. `ls /sys/class/net` should show `wlan1` and `wlan2` beside `wlan0`.
4. Reboot. The Pi now broadcasts **Riser-Sidekick-XXXX**.

## Survey

1. In Airwave open the floor → **Inspect** (nothing selected) → **Riser Sidekick → Pair a Sidekick**. A 6-digit code appears.
2. On your phone join the Sidekick hotspot and open **http://10.42.0.1**. Enter the code. (The Pi needs internet for this step: keep Ethernet plugged in, or use *client mode* on the page to join office WiFi.)
3. Tap **Refresh floors** once while online so floor plans are cached on the box.
4. Choose the floor, tap where you are standing, tap **Record here**. Walk 3–5 m, repeat. Each point takes about 2–4 s to scan all bands.
5. Tap **Done**. Points upload automatically whenever the box is online, or tap **Sync points now**.
6. Back in Airwave, the **Measured** view appears next to Signal / SNR / Overlap.

## How it scans

Passive `iw` scans only; the MT7921 driver can reset when tools send active probes. With two radios, one sweeps 5 GHz while the other sweeps 2.4 + 6 GHz, and the strongest reading per BSSID is kept. The country code (default `AE`) is applied at install so 6 GHz is scannable.

## Layout

```
sidekickd/
  server.py      aiohttp app: survey page + /api/* (status, pair, floors, scan, points, sync, network)
  scanner.py     radio discovery, passive iw scans, parser
  store.py       SQLite queue of points, cached floors and plan images
  airwave.py     pairing, floor download, point upload
  config.py      /etc/riser-sidekick/config.json
  static/        survey page (single file, phone first)
install.sh       packages, venv, hotspot, systemd service
system/          systemd unit
```

Logs: `journalctl -u riser-sidekick -f`. Config: `/etc/riser-sidekick/config.json`. Data: `/var/lib/riser-sidekick/`.

## Roadmap

- Monitor-mode capture for channel utilisation and retry rates
- tinySA Ultra sweeps for non-WiFi interference
- GPS for outdoor surveys
- A small e-paper status display and a Riser case
