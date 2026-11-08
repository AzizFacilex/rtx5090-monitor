# rtx5090-monitor

GNOME top-bar indicator and terminal dashboard for the **ASUS ROG Astral RTX 5090**, showing
per-pin 12V-2x6 (12VHPWR) connector current alongside GPU temperature and power.

```
 ▣ 8.3A  71°C  587W        ← top bar: worst pin current · GPU temp · board power
```

Clicking it opens a menu with:

- the **astral-guard verdict** (OK / WARNING / CRITICAL) and any findings
- **current and voltage for each of the six pins**, total connector watts and load balance between pins
- GPU temperature, power draw and limit, load, VRAM, clock, fan, and the active **throttle reason**
- shortcuts to the full GPU Monitor, ComfyUI and the guard log
- **Cancel pending shutdown**: appears, and the bar shows `⛔ SHUTDOWN`, during astral-guard's 30 s poweroff countdown
- **Turn monitoring off/on**: stops or starts `astral-guard.timer`. Off lasts only until the next reboot, so protection always comes back, and the bar shows `MON OFF` meanwhile
- **Exit indicator**

The icon changes on a warning or a critical finding. When the verdict gets worse, a desktop notification pops up.

**Windows?** See [`windows/`](windows/README.md): the same indicator, guard and dashboard, using HWiNFO64 for the per-pin data.

## Requirements

- Ubuntu with GNOME and the AppIndicator extension (`ubuntu-appindicators@ubuntu.com`, on by default)
- NVIDIA driver with `nvidia-smi`
- [astral-hwmon](https://github.com/ksokolowski/astral-hwmon) driver + `astral-guard` for the per-pin data.
  Without it the GPU stats still work and the pins show as unavailable.

## Install / remove

```sh
./install.sh     # installs gir1.2-ayatanaappindicator3-0.1 via apt if missing
./uninstall.sh
```

`gpu-monitor` is the full-screen terminal version of the same data.

## Permissions

`install.sh` adds `/etc/polkit-1/rules.d/50-astral-guard-indicator.rules` so the menu can act without
a password prompt. A password dialog could eat the 30 s cancel window. The rule grants an active,
local member of the `sudo` group exactly two things: start/stop of `astral-guard.timer` and **stop** of
`astral-guard-poweroff.service`. Nothing else.

## Safety note

This is a **display** tool and only reads data. Protection, meaning an automatic poweroff on a CRITICAL
verdict, comes from astral-guard's systemd units, not from this indicator. The thresholds shown
here are the ones `astral-guard --json` reports: warning at 9.2 A per pin, critical at 9.5 A.
The sensor measures current, not connector temperature.

Tested on: ROG Astral RTX 5090 OC White (`1043:8A2E`), Ubuntu 26.04, GNOME 50, driver 615.71.

## License

MIT, see [LICENSE](LICENSE). The Windows guard rules are ported from
[astral-hwmon](https://github.com/ksokolowski/astral-hwmon)'s astral-guard (MIT, © Krzysztof Sokołowski).
