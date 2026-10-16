#!/usr/bin/env bash
# Riser Sidekick installer for Raspberry Pi OS (Bookworm or newer, 64-bit).
# Run once as root on a fresh Pi:  sudo bash install.sh
set -euo pipefail
trap 'echo; echo "ERROR: install.sh failed at line $LINENO: $BASH_COMMAND" >&2' ERR

APP=/opt/riser-sidekick
COUNTRY="${SIDEKICK_COUNTRY:-AE}"
HOTSPOT_PW="${SIDEKICK_HOTSPOT_PASSWORD:-risersurvey}"

if [[ $EUID -ne 0 ]]; then echo "Run with sudo"; exit 1; fi
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "== Packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv iw network-manager avahi-daemon

echo "== Regulatory domain ${COUNTRY} (needed for 6 GHz)"
raspi-config nonint do_wifi_country "${COUNTRY}" || true
iw reg set "${COUNTRY}" || true

echo "== App files"
mkdir -p "${APP}" /etc/riser-sidekick /var/lib/riser-sidekick
rsync -a --delete --exclude venv --exclude .git "${SRC}/sidekickd" "${APP}/"
cp "${SRC}/requirements.txt" "${APP}/"
if [[ ! -d "${APP}/venv" ]]; then python3 -m venv "${APP}/venv"; fi
"${APP}/venv/bin/pip" install -q --upgrade pip
"${APP}/venv/bin/pip" install -q -r "${APP}/requirements.txt"

echo "== Hostname riser-sidekick (reach it at riser-sidekick.local)"
hostnamectl set-hostname riser-sidekick
sed -i 's/^127.0.1.1.*/127.0.1.1\triser-sidekick/' /etc/hosts || true

echo "== Hotspot on the built-in radio (wlan0)"
# (python, not tr|head: head closing the pipe trips pipefail and silently aborts the script)
SSID="Riser-Sidekick-$(python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4)))")"
if ! nmcli -t -f NAME con show | grep -q '^Sidekick-Hotspot$'; then
  nmcli con add type wifi ifname wlan0 con-name Sidekick-Hotspot autoconnect yes ssid "${SSID}" \
    802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv6.method disabled \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "${HOTSPOT_PW}" >/dev/null
  nmcli con modify Sidekick-Hotspot connection.autoconnect-priority 10
else
  SSID="$(nmcli -g 802-11-wireless.ssid con show Sidekick-Hotspot)"
fi
# Keep the scan radios out of NetworkManager's hands.
cat > /etc/NetworkManager/conf.d/90-riser-sidekick.conf <<'CONF'
[keyfile]
unmanaged-devices=driver:mt7921u;driver:mt7925u;driver:mt76x2u
CONF
systemctl reload NetworkManager || true

if [[ ! -f /etc/riser-sidekick/config.json ]]; then
  cat > /etc/riser-sidekick/config.json <<JSON
{
  "airwave_url": "${SIDEKICK_AIRWAVE_URL:-https://riser-airwave.vercel.app}",
  "country": "${COUNTRY}",
  "hotspot_ssid": "${SSID}",
  "hotspot_password": "${HOTSPOT_PW}"
}
JSON
  chmod 600 /etc/riser-sidekick/config.json
fi

echo "== Service"
cp "${SRC}/system/riser-sidekick.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now riser-sidekick

echo
echo "Done. Hotspot: ${SSID}  password: ${HOTSPOT_PW}"
echo "On your phone: join the hotspot, open http://10.42.0.1  (or http://riser-sidekick.local)"
echo "Radios detected: $(for p in /sys/class/net/wl*; do d=$(basename "$(readlink -f "$p/device/driver" 2>/dev/null)" 2>/dev/null); [[ -n "$d" && "$d" != brcmfmac ]] && echo -n "$(basename "$p")($d) "; done)"
