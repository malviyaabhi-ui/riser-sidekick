"""Device configuration stored at /etc/riser-sidekick/config.json."""
from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, asdict, field
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("SIDEKICK_CONFIG", "/etc/riser-sidekick/config.json"))
DATA_DIR = Path(os.environ.get("SIDEKICK_DATA", "/var/lib/riser-sidekick"))
FIRMWARE = "sidekick-0.1.0"


@dataclass
class Config:
    airwave_url: str = "https://riser-airwave.vercel.app"
    token: str = ""                 # rsk_... issued at pairing
    device_id: str = ""
    device_name: str = "Riser Sidekick"
    org_name: str = ""
    country: str = "AE"             # regulatory domain; needed for 6 GHz
    hotspot_ssid: str = field(default_factory=lambda: f"Riser-Sidekick-{socket.gethostname()[-4:]}")
    hotspot_password: str = "risersurvey"
    scan_interfaces: list[str] = field(default_factory=list)  # empty = auto-detect mt7921u radios

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                for k, v in data.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
            except (OSError, ValueError):
                pass
        return cfg

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(CONFIG_PATH)

    @property
    def paired(self) -> bool:
        return bool(self.token and self.device_id)
