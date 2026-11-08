# rtx5090-monitor for Windows

Windows port of the Ubuntu indicator: a tray icon, a background guard and a terminal dashboard
for the **ASUS ROG Astral RTX 5090**, showing per-pin 12V-2x6 (12VHPWR) connector current
alongside GPU temperature and power. The rules are the same and so are the thresholds.

| Ubuntu | Windows |
|---|---|
| `astral-hwmon` kernel driver | **HWiNFO64** reads the card's pin sensor and reports it to the registry ("Gadget") |
| `astral-guard` + `astral-guard.timer` | `astral-guard.py --daemon`, started at sign-in, checks every 15 s |
| `astral-guard-poweroff.service` | `shutdown /s /t 30` on a CRITICAL verdict, cancellable |
| GNOME top-bar indicator | tray icon: worst pin current, coloured by verdict; full line in the tooltip |
| `gpu-monitor` (`watch`) | `gpu-monitor.py` console dashboard |
| polkit rule | not needed: a user can schedule/abort a shutdown and stop their own guard |

```
 [8.6]   tooltip: RTX 5090  8.6A  71°C  587W  [OK]
  green = OK · amber = WARNING · red = CRITICAL · grey = sensor unavailable
  dark with coloured ring = monitoring OFF · "SD" = shutdown pending
```

Right-click the icon for:

- the **guard verdict** (OK / WARNING / CRITICAL / UNKNOWN) and any findings
- **current and voltage for each of the six pins**, connector watts and the balance between pins
- GPU temperature, power draw and limit, load, VRAM, clock, fan, and the active **throttle reason**
- Open GPU Monitor (also the left-click action), Open HWiNFO64, Guard log, and Open ComfyUI if configured
- **STOP CANCEL PENDING SHUTDOWN**: appears during the 30 s countdown after a CRITICAL verdict
- **Turn monitoring off/on**: stops or starts the background guard. Off lasts only until the next sign-in, so protection always comes back
- **Exit indicator**

A notification pops up whenever the verdict gets worse.

## Requirements

- Windows 10/11, NVIDIA driver (`nvidia-smi` is included)
- Python 3.9+ in `PATH`
- [HWiNFO64](https://www.hwinfo.com/) (free) for the per-pin data. Without it the GPU stats still work and the pins show as unavailable.

## HWiNFO setup (once)

1. Install it: `winget install REALiX.HWiNFO`, then start it and choose **Sensors-only**.
2. In the sensors window, find the ROG Astral's **12V-2x6 / pin current** readings (six of them,
   plus six pin voltages if your HWiNFO version shows them).
3. Open **Sensor settings → HWiNFO Gadget** and tick **Enable reporting to Gadget**. Then select each
   of the six pin currents (and the six pin voltages) and tick **Report value in Gadget**.
4. Optional but recommended: **Sensor settings → General → Polling period 1000 ms**, and in the main
   settings **Auto Start** + **Minimize Sensors on Startup**, so it is running after every boot.
5. Check the mapping:

   ```
   python astral-guard.py --list-sensors
   ```

   The six pin entries should be marked `PIN`. A pin number is recognised in the label with
   `pin_regex` (default: "Pin 3", "Pin3", "Pin #3"). If your labels differ, rename them in HWiNFO or
   change `pin_regex` in `config.json`.

Use the Gadget registry interface instead of HWiNFO's shared memory: shared memory in the free
version switches itself off every 12 hours, and a guard that silently goes blind is worse than none.

Run only one program that polls the card's pin sensor. GPU Tweak III's Power Detector+ and HWiNFO
reading the same chip at the same time can produce glitches. Afterburner alongside HWiNFO is fine.

## Install / remove

```
powershell -ExecutionPolicy Bypass -File install.ps1     # pip installs pystray + Pillow (per user)
powershell -ExecutionPolicy Bypass -File uninstall.ps1   # -Purge also deletes config and log
```

No admin rights are needed. It installs to `%LOCALAPPDATA%\rtx5090-monitor\app`, starts the guard and the
indicator at sign-in (HKCU Run key), and adds Start menu shortcuts for GPU Monitor, GPU Indicator and
Guard log.

`config.json` in `%LOCALAPPDATA%\rtx5090-monitor` (edits apply without a restart):

| key | default | |
|---|---|---|
| `check_every_s` | 15 | guard cadence |
| `samples` / `sample_interval_ms` | 5 / 1000 | a finding must hold in every sample |
| `auto_shutdown` | true | false = warn only |
| `shutdown_delay_s` | 30 | the cancel window |
| `comfyui` | "" | command for the menu entry, e.g. `["C:\\ComfyUI\\run_nvidia_gpu.bat"]` |
| `pin_regex`, `sensor_regex` | | how pins are found in HWiNFO's Gadget list |
| `limits` | {} | override thresholds, e.g. `{"pin_warn_ma": 9000}` |

## Safety note

The indicator is a **display** tool and only reads data. Protection comes from the guard: on a
CRITICAL verdict it runs `shutdown /s /t 30`. Windows announces this, and it can be cancelled from the tray or with
`shutdown /a`. If the reading is still critical at the next check, it is scheduled again, as on Ubuntu.
A user in a full-screen game may not see the warning, so the 30 s are the whole margin.

Only CRITICAL acts. UNKNOWN (HWiNFO closed, Gadget reporting off, a pin missing, an implausible
value) never shuts the machine down. It fails towards staying on, so keep an eye on the grey icon.

The rules are a direct port of [astral-guard](https://github.com/ksokolowski/astral-hwmon)'s
`guard_eval.c` (MIT) and are tested against its own case corpus (`tests/`):

| rule | trips at |
|---|---|
| per-pin current | WARN 9.2 A, CRIT 9.5 A |
| open pin | one pin under 0.5 A with ≥ 10 A flowing → CRIT |
| min/max imbalance (≥ 20 A flowing) | NOTE < 85 %, WARN < 70 %, CRIT < 60 % |
| pin voltage floor (if HWiNFO reports pin voltages) | WARN 11.4 V, CRIT 11.0 V |

```
python -m unittest discover -s tests
python astral-guard.py --json            # one check, astral-guard's exit codes 0/1/2/3
python astral-guard.py --daemon --dry-run  # logs the shutdown instead of doing it
```

The sensor measures current, not connector temperature.
