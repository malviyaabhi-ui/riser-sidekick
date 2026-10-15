"""Quick self-test of the iw scan parser (runs anywhere, no radio needed)."""
from sidekickd.scanner import parse_scan, band_for_freq, channel_for_freq

SAMPLE = """BSS 3c:84:6a:11:22:33(on wlan1)
\tTSF: 0 usec
\tfreq: 5180
\tsignal: -47.00 dBm
\tSSID: Riser-Corp
\tHT operation:
\t\t * primary channel: 36
\tVHT operation:
\t\t * channel width: 1 (80 MHz)
BSS 3c:84:6a:11:22:34(on wlan1)
\tfreq: 2437
\tsignal: -61.00 dBm
\tSSID: Riser-Guest
BSS 3c:84:6a:11:22:35(on wlan2)
\tfreq: 6115
\tsignal: -58.50 dBm
\tSSID: Riser-6E
"""

rs = parse_scan(SAMPLE)
assert [r.band for r in rs] == ["5", "2.4", "6"], rs
assert rs[0].channel == 36 and rs[0].width_mhz == 80
assert rs[1].channel == 6
assert rs[2].channel == 33 and rs[2].rssi == -58.5
assert band_for_freq(5955) == "6" and channel_for_freq(5955) == 1
print("scanner parser OK:", [(r.ssid, r.band, r.channel, r.rssi) for r in rs])
