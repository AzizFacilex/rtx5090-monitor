# rtx5090-monitor

Connector monitor for the **ASUS ROG Astral RTX 5090**, for **Ubuntu (GNOME)** and **Windows 10/11**.

It shows the current on each of the six 12 V pins of the 12V-2x6 (12VHPWR) power connector
alongside GPU temperature and power. A background guard checks the connector every 15 seconds
and shuts the PC down when it finds a CRITICAL fault: a pin overloaded, a pin that stopped
conducting, a large imbalance between pins, or the 12 V rail sagging. You get a 30-second
window to cancel.

```
Ubuntu top bar:   ▣ 8.3A  71°C  587W           ← worst pin current · GPU temp · board power
Windows tray:     [8.3]  tooltip: RTX 5090  8.3A  71°C  587W  [OK]
```

The Astral is the RTX 5090 with a current sensor on every pin of the power connector. Uneven
current, with one or two pins carrying far more than their share, is how these connectors melt,
and only a per-pin reading shows it. A connector can look fine on total power while one pin is
overloaded.

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Linux installation (Ubuntu)](#linux-installation-ubuntu)
- [Windows installation](#windows-installation)
- [Using it](#using-it)
- [The rules and thresholds](#the-rules-and-thresholds)
- [Safety notes](#safety-notes)
- [Troubleshooting](#troubleshooting)
- [Development and tests](#development-and-tests)
- [Repository layout](#repository-layout)
- [License](#license)

## What you get

| | Ubuntu | Windows |
|---|---|---|
| Status at a glance | top-bar label: worst pin A, °C, W | tray icon: worst pin A, coloured by verdict; full line in tooltip |
| Menu | verdict and findings, per-pin A/V, connector W and balance, GPU temp, power and limit, load, VRAM, clock, fan, throttle reason | same |
| Notifications | when the verdict gets worse | same |
| Auto shutdown on CRITICAL | yes, 30 s cancel window | yes, 30 s cancel window |
| Cancel from the menu | **Cancel pending shutdown** | **STOP CANCEL PENDING SHUTDOWN** |
| Monitoring off/on | until next reboot | until next sign-in |
| Terminal dashboard | `gpu-monitor` | GPU Monitor (Start menu) |
| Guard log | journald | `%LOCALAPPDATA%\rtx5090-monitor\guard.log` |

## How it works

Three layers, the same on both systems. Each one can run without the one above it.

| Layer | Ubuntu | Windows |
|---|---|---|
| **Sensor**: reads the six pin currents and voltages from the card | [astral-hwmon](https://github.com/ksokolowski/astral-hwmon) kernel driver | [HWiNFO64](https://www.hwinfo.com/) (free), values shared through its "Gadget" registry interface |
| **Guard**: applies the rules and shuts the PC down on CRITICAL | `astral-guard` + systemd timer every 15 s + `astral-guard-poweroff.service` | `astral-guard.py --daemon`, started at sign-in, every 15 s, then `shutdown /s /t 30` |
| **Display**: shows it all, cancels, toggles | `gpu-indicator` (GNOME AppIndicator) | `gpu-indicator.pyw` (system tray) |

GPU stats come from `nvidia-smi` on both. The indicator only reads data; the guard is what
protects. The Windows guard uses a line-for-line port of astral-guard's rules and is tested
against astral-guard's own test cases, so both systems give the same verdict on the same readings.

## Linux installation (Ubuntu)

Tested on Ubuntu 26.04, GNOME 50, NVIDIA driver 615.71, ROG Astral RTX 5090 OC White (`1043:8A2E`).

### 1. Prerequisites

You need a working NVIDIA driver (`nvidia-smi` must print your card) and the AppIndicator GNOME
extension, which Ubuntu enables by default (`ubuntu-appindicators@ubuntu.com`).

```sh
sudo ubuntu-drivers install            # skip if nvidia-smi already works; reboot afterwards
sudo apt install git build-essential dkms linux-headers-$(uname -r) lm-sensors
nvidia-smi                              # must list the RTX 5090
```

### 2. The per-pin sensor driver (astral-hwmon)

```sh
cd ~
git clone https://github.com/ksokolowski/astral-hwmon.git
cd astral-hwmon
make dkms-install          # builds, signs and installs via DKMS; survives kernel upgrades
sensors "astral12vhpwr-*"  # six currents and six voltages should appear
```

**Secure Boot:** DKMS signs the module with your MOK key, but the key must be enrolled once or
the kernel refuses to load it:

```sh
sudo mokutil --import /var/lib/shim-signed/mok/MOK.der   # choose a one-time password
sudo reboot                                              # blue MOK screen: Enroll MOK → Continue → password
```

The module loads automatically on machines with a supported card. To try it without installing,
run `make module && make module-load`.

### 3. The rule checker (astral-guard)

Still in `~/astral-hwmon`:

```sh
make guard
sudo make install-guard    # installs /usr/local/bin/astral-guard
astral-guard               # e.g.  OK 12VHPWR /sys/class/hwmon/hwmon10
astral-guard --json        # the report the indicator reads
```

Exit codes: 0 OK, 1 WARNING, 2 CRITICAL, 3 UNKNOWN (driver not loaded or a channel unreadable).

### 4. Automatic protection (systemd)

astral-hwmon ships the units as opt-in examples. These commands install them and set them up
the way this project expects: a check every 15 s, and poweroff on CRITICAL after 30 s.

```sh
cd ~/astral-hwmon
sudo install -m 644 examples/astral-guard.service examples/astral-guard.timer \
                    examples/astral-guard-poweroff.service /etc/systemd/system/
sudo install -m 755 examples/astral-guard-notify.sh /usr/local/bin/astral-guard-notify

# Arm the poweroff. Two edits, and both are required: OnFailure= starts the poweroff unit;
# SuccessExitStatus=1 3 makes sure only CRITICAL (exit 2) can trigger it, not UNKNOWN.
sudo sed -i 's/^# OnFailure=/OnFailure=/; s/^# SuccessExitStatus=/SuccessExitStatus=/' \
  /etc/systemd/system/astral-guard.service

# 30 s grace period instead of 60, with a desktop notification.
sudo sed -i 's/in 60 seconds/in 30 seconds/;
             s|^ExecStartPre=/usr/bin/sleep 60|ExecStartPre=/usr/bin/sleep 30|;
             s|^# ExecStartPre=-/usr/local/bin/astral-guard-notify 60|ExecStartPre=-/usr/local/bin/astral-guard-notify 30|' \
  /etc/systemd/system/astral-guard-poweroff.service

# Check every 15 s instead of every 5 min, starting 30 s after boot.
sudo sed -i 's/^OnBootSec=.*/OnBootSec=30s/; s/^OnUnitActiveSec=.*/OnUnitActiveSec=15s/;
             s/^AccuracySec=.*/AccuracySec=1s/' /etc/systemd/system/astral-guard.timer

sudo systemctl daemon-reload
sudo systemctl enable --now astral-guard.timer
```

Check that the edits took effect and the timer is running:

```sh
grep -E '^(OnFailure|SuccessExitStatus)' /etc/systemd/system/astral-guard.service   # two lines
grep -E '^ExecStartPre=/usr/bin/sleep' /etc/systemd/system/astral-guard-poweroff.service  # sleep 30
systemctl list-timers astral-guard.timer        # next run within 15 s
journalctl -u astral-guard -n 5                 # recent verdicts
```

Starting the poweroff unit by hand is safe and does nothing: it only proceeds when systemd started
it because astral-guard exited with CRITICAL. That is astral-guard's interlock.

### 5. The indicator and dashboard (this repo)

```sh
cd ~
git clone https://github.com/AzizFacilex/rtx5090-monitor.git
cd rtx5090-monitor
./install.sh
```

`install.sh`:
- installs `gir1.2-ayatanaappindicator3-0.1` and `libnotify-bin` with apt if they are missing
- installs a polkit rule to `/etc/polkit-1/rules.d/50-astral-guard-indicator.rules` so the menu can
  cancel a shutdown and toggle monitoring without a password prompt, since a password dialog could
  eat the 30 s window. It allows an active, local member of the `sudo` group to do exactly two things:
  start/stop `astral-guard.timer`, and **stop** `astral-guard-poweroff.service`. Nothing else.
- copies `gpu-indicator` and `gpu-monitor` to `~/.local/bin`, adds both to the app grid and the
  indicator to autostart, then starts the indicator

The indicator appears in the top bar right away and at every login. `gpu-monitor` in a terminal
opens the full-screen dashboard.

The **Open ComfyUI** menu entry runs `~/ComfyUI/launch-desktop.sh`. Edit `bin/gpu-indicator`
before installing if yours lives elsewhere.

### Update / uninstall (Linux)

```sh
cd ~/rtx5090-monitor && git pull && ./install.sh     # update
./uninstall.sh                                       # remove indicator, dashboard, polkit rule
```

`uninstall.sh` leaves astral-hwmon and the guard units alone. To remove those too:

```sh
sudo systemctl disable --now astral-guard.timer
sudo rm /etc/systemd/system/astral-guard{.service,.timer,-poweroff.service} /usr/local/bin/astral-guard-notify
sudo systemctl daemon-reload
cd ~/astral-hwmon && make dkms-remove
```

## Windows installation

Tested on Windows 11, NVIDIA driver 610.88, HWiNFO64, ROG Astral RTX 5090 OC White (`1043:8A2E`).
No admin rights are needed for this project. HWiNFO itself asks for them.

### 1. Prerequisites

- **NVIDIA driver**: `nvidia-smi` is included with it. Check with `nvidia-smi` in PowerShell.
- **Python 3.9 or newer**, in `PATH`:
  ```powershell
  winget install Python.Python.3.12
  ```
  Or use the python.org installer and tick **Add python.exe to PATH**. Open a new terminal and
  check `python --version`. If that opens the Microsoft Store instead, turn off the `python.exe`
  aliases in **Settings → Apps → Advanced app settings → App execution aliases**.
- **Git** (optional; you can download the ZIP instead): `winget install Git.Git`

### 2. HWiNFO64, the per-pin sensor

```powershell
winget install REALiX.HWiNFO
```

1. Start **HWiNFO64** and choose **Sensors-only**.
2. Scroll to **dGPU [#1]: NVIDIA GeForce RTX 5090**. It lists **GPU 12VHPWR Pin1 Current** to
   **Pin6 Current** and **GPU 12VHPWR Pin1 Voltage** to **Pin6 Voltage**.
3. Click the gear (**Sensor settings**) → **HWiNFO Gadget** tab:
   - tick **Enable reporting to Gadget**
   - select each of the 12 entries above in the list and tick **Report value in Gadget**
   - **OK**
4. Sensor settings → **General** → **Polling period**: `1000` ms (the default 2000 works too,
   but 1000 gives the guard more samples).
5. Main HWiNFO **Settings** → tick **Auto Start** and **Minimize Sensors on Startup**. HWiNFO
   then starts minimised after every sign-in. Without it, the guard has no data after a reboot.

The guard uses the Gadget interface rather than HWiNFO's shared memory on purpose. In the free
version, shared memory switches itself off after 12 hours, and a guard that quietly loses its
data is worse than none.

**Run only one program that reads the pin sensor.** Close ASUS GPU Tweak III (or at least turn off
its Power Detector+); two tools reading the same sensor chip at once can produce glitches.
MSI Afterburner alongside HWiNFO is fine.

### 3. Get the code

```powershell
cd $HOME\source\repos           # or anywhere you like
git clone https://github.com/AzizFacilex/rtx5090-monitor.git
cd rtx5090-monitor\windows
```

### 4. Check the sensor mapping

```powershell
python -m pip install --user pystray Pillow
python astral-guard.py --list-sensors
```

All twelve entries should be marked `PIN`, ending with a line like:

```
result: currents mA [260, 260, 260, 260, 260, 260], voltages mV [12040, 12040, 12040, 12040, 12040, 12048]
```

If none are marked, Gadget reporting is off or the entries aren't ticked (step 2.3). If HWiNFO uses
different labels on your system, see [Troubleshooting](#troubleshooting).

Then run a one-off check:

```powershell
python astral-guard.py          # astral-guard: OK  + the pin values; exit code 0/1/2/3
```

### 5. Install

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1`:
- installs `pystray` and `Pillow` for your user with pip
- copies the program to `%LOCALAPPDATA%\rtx5090-monitor\app`
- creates `%LOCALAPPDATA%\rtx5090-monitor\config.json` if it doesn't exist yet
- registers the **guard** and the **tray indicator** to start at sign-in
  (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`)
- adds a **Start menu → RTX 5090 Monitor** folder with GPU Monitor, GPU Indicator and Guard log
- starts the guard and the indicator

The icon lands in the tray overflow (`^`). Drag it onto the taskbar to keep it visible, or turn it
on under **Settings → Personalization → Taskbar → Other system tray icons**.

### 6. Check it works

- Hover over the icon. The tooltip shows `RTX 5090  0.3A  30°C  25W  [OK]` or similar.
- Right-click it. The menu shows **12V-2x6 guard: OK** and six pin rows with amps and volts.
- **Guard log** shows `guard started` followed by `verdict OK`.
- Run a game or a render and open **GPU Monitor**. The six pin currents should rise **and differ
  slightly from each other**. If all six stay exactly equal under load, see
  [Troubleshooting](#troubleshooting).

To see the shutdown path without risking anything, turn monitoring off in the tray menu, then:

```powershell
python astral-guard.py --daemon --dry-run    # logs "DRY RUN: would run shutdown" instead of shutting down
```

With healthy readings it logs `verdict OK` and does nothing; stop it with Ctrl+C and turn monitoring
back on. [Development and tests](#development-and-tests) shows how to feed it a critical reading.

### Configuration (Windows)

`%LOCALAPPDATA%\rtx5090-monitor\config.json`. The guard picks up changes at its next check,
and the indicator does too.

| Key | Default | Meaning |
|---|---|---|
| `check_every_s` | `15` | how often the guard checks |
| `samples` / `sample_interval_ms` | `5` / `1000` | samples per check; a finding must hold in all of them |
| `auto_shutdown` | `true` | `false` = notify only, never shut down |
| `shutdown_delay_s` | `30` | the cancel window |
| `comfyui` | `""` | command for an **Open ComfyUI** menu entry, e.g. `"C:\\ComfyUI\\run_nvidia_gpu.bat"` |
| `pin_regex` | `(?i)\bpin\s*#?\s*([1-6])\b` | how the pin number is found in an HWiNFO label |
| `sensor_regex` | `""` | only use HWiNFO entries whose sensor name matches (if several devices report "pins") |
| `hwinfo_key` | `Software\HWiNFO64\VSB` | registry key HWiNFO's Gadget values are in |
| `limits` | `{}` | threshold overrides, e.g. `{"pin_warn_ma": 9000}` |

### Update / uninstall (Windows)

```powershell
cd $HOME\source\repos\rtx5090-monitor; git pull
powershell -ExecutionPolicy Bypass -File windows\install.ps1      # update: stops, copies, restarts
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1    # remove; keeps config.json and guard.log
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1 -Purge   # also deletes config and log
```

## Using it

### The status

| Ubuntu label | Windows icon | Meaning |
|---|---|---|
| `8.3A 71°C 587W`, normal icon | green with the worst pin's amps | OK |
| warning icon | amber | WARNING: something is off, the PC keeps running |
| error icon | red | CRITICAL: shutdown is triggered |
| `—A`, question icon | grey `--` | UNKNOWN: no per-pin data (driver not loaded / HWiNFO not running) |
| `MON OFF …` | dark, with a coloured ring | the background guard is off |
| `⛔ SHUTDOWN …` | red `SD` with a white ring | shutdown pending: cancel now if you want to |

### The menu

- **Guard verdict** and the findings behind it, e.g. `pin 5 at 9600 mA, at or above the 9500 mA rating`.
- **Pin 1 to 6**: current and voltage; `⚠`/`⛔` (Linux) or `[WARN]`/`[CRIT]` (Windows) marks a pin over a threshold.
- **Connector**: total watts through the connector and the **balance** (lowest pin ÷ highest pin;
  near 100% is good; it's only meaningful under load).
- **GPU**: temperature, power draw / limit, load, VRAM, core clock, fan, and the active throttle
  reason (power cap, thermal, power brake…).
- **Open GPU Monitor**: the full dashboard in a terminal. On Windows this is also the left-click action.
- **Open ComfyUI** (Linux always; Windows if `comfyui` is set), **Open HWiNFO64** (Windows).
- **Guard log**: live log of verdicts and actions.
- **Cancel pending shutdown**: only visible during the 30 s countdown.
- **Turn monitoring off / on**: pauses the background guard. Off lasts only until the next reboot
  (Linux) or sign-in (Windows), so protection always comes back. The status shows `MON OFF` meanwhile.
- **Exit indicator**: closes the display only. The guard keeps protecting.

### When a shutdown is pending

1. You get a notification, and the status shows SHUTDOWN. Windows also shows its own "about to
   shut down" message.
2. To keep the PC on, use **Cancel pending shutdown** in the menu. As a fallback, run
   `sudo systemctl stop astral-guard-poweroff.service` on Linux or `shutdown /a` on Windows.
3. **Stop the load** (close the game or render). If the reading is still critical at the next check,
   15 s later, the shutdown is scheduled again. That's deliberate.
4. Power off and **inspect the cable at both ends**: fully seated with a click, no gap, no bend
   within the first few cm of the plug, no discoloured or melted plastic. Reseat it or replace the cable
   before heavy loads again. Use the PSU's native 12V-2x6 cable, not an adapter.

## The rules and thresholds

Every check takes several samples, and a finding counts only if it holds in **every** sample, so
a single odd reading never triggers anything.

| Rule | Trips at | Source |
|---|---|---|
| Per-pin current | WARNING ≥ 9.2 A, CRITICAL ≥ 9.5 A | ASUS Power Detector+; the 12V-2x6 per-pin rating |
| Open pin | one pin < 0.5 A while ≥ 10 A flows in total → CRITICAL | ASUS Power Detector+ ("or is at 0 amps") |
| Imbalance, lowest ÷ highest pin (≥ 20 A total) | NOTE < 85 %, WARNING < 70 %, CRITICAL < 60 % | Thermal Grizzly WireView Pro II |
| Pin voltage floor | WARNING < 11.4 V, CRITICAL < 11.0 V | ATX 12 V tolerance |

NOTE is advisory: it shows in the findings but never changes the verdict. Only CRITICAL shuts the PC
down. The rules and their reasoning come from
[astral-guard](https://github.com/ksokolowski/astral-hwmon/blob/main/guard/README.md).

## Safety notes

- **The sensor measures current, not temperature.** A green verdict is not a guarantee about
  connector heat.
- **Only CRITICAL acts.** UNKNOWN (no driver, HWiNFO closed, a pin missing, an implausible value) never
  shuts the PC down, so a broken sensor can't power off a working machine. The downside is that
  a grey/unknown status means **you are not protected**. Keep an eye on it.
- **The 30 s window is the whole margin.** In a full-screen game you may miss the warning, and unsaved
  work is lost when the PC shuts down. That's the trade-off for protection while nobody is watching.
  Set `auto_shutdown` to `false` (Windows) or skip step 4 (Linux) if you only want warnings.
- **Linux protection runs as systemd units, independent of the indicator.** Closing the indicator
  doesn't stop it. On Windows the guard is also its own process, but it runs in your session, so it
  starts at sign-in, not at boot.
- This is a monitoring tool, not a substitute for a correctly seated, undamaged native cable.

## Troubleshooting

**Pins show as unavailable / grey icon / UNKNOWN**
- Linux: `sensors "astral12vhpwr-*"` prints nothing → the driver isn't loaded. Run `sudo modprobe
  astral-hwmon` and check `dmesg | grep -i astral`. With Secure Boot on, the MOK key isn't enrolled (step 2).
- Windows: the menu row says why: `HWiNFO64 is not running` → start it (and enable Auto Start).
  `Gadget reporting is off` → step 2.3. `only N of 6 pin currents` → one of the entries isn't ticked
  for Gadget.

**`--list-sensors` finds entries but marks none as PIN** (Windows)
The labels don't contain "Pin1"… Rename them in HWiNFO's sensor window or set
`pin_regex` in `config.json`. `pin N … reported twice` means two devices report pins: set
`sensor_regex`, e.g. `"RTX 5090"`.

**All six pins always show exactly the same value, even under load** (Windows)
At idle that's normal. Under load the pins should differ slightly. If they stay identical, your HWiNFO
version is reporting an average instead of each pin. The over-current limits still work, but the
imbalance and open-pin rules can't see anything. Update HWiNFO.

**Tray icon missing** (Windows): it's in the overflow (`^`). Drag it to the taskbar. If it isn't
there at all, start **Start menu → RTX 5090 Monitor → GPU Indicator**. Only one copy runs at a time.

**`install.ps1 cannot be loaded because running scripts is disabled`**: run it as shown, with
`powershell -ExecutionPolicy Bypass -File install.ps1`.

**Cancel / monitoring toggle asks for a password** (Linux): the polkit rule is missing or you
aren't in the `sudo` group. Re-run `./install.sh` and check with `groups`.

**The guard never seems to run** (Linux): `systemctl list-timers astral-guard.timer` and
`journalctl -u astral-guard -e`. Exit 203 means `/usr/local/bin/astral-guard` is missing (step 3).

## Development and tests

Windows port (no card or HWiNFO needed):

```powershell
cd windows
python -m unittest discover -s tests        # rules vs astral-guard's own case corpus + HWiNFO parsing
```

Feeding the Windows tools a fake reading. The `RTX5090_HOME` folder isolates state and log from
a real install:

```powershell
$env:RTX5090_HOME = "$env:TEMP\rtxtest"; mkdir $env:RTX5090_HOME -Force
'{"ma":[7640,7840,8300,7920,9600,8020],"mv":[11960,11944,11952,11944,11944,11944]}' |
  Set-Content "$env:RTX5090_HOME\crit.json"
$env:RTX_FAKE_SENSORS = "$env:RTX5090_HOME\crit.json"
python astral-guard.py                      # CRITICAL, exit 2
python astral-guard.py --daemon --dry-run   # logs DRY RUN shutdown to $env:RTX5090_HOME\guard.log
```

The Linux sensor and guard are tested in
[astral-hwmon](https://github.com/ksokolowski/astral-hwmon) (`make test-guard`, `make test-hw`).

## Repository layout

```
bin/gpu-indicator         Linux top-bar indicator (Python, GTK/AppIndicator)
bin/gpu-monitor           Linux terminal dashboard
desktop/                  .desktop files (app grid + autostart)
polkit/                   rule for password-free cancel / toggle
install.sh, uninstall.sh  Linux install for the current user
windows/astral_core.py    HWiNFO reader, nvidia-smi reader, astral-guard rules (port)
windows/astral-guard.py   Windows guard: one-shot check, --json, --list-sensors, --daemon
windows/gpu-indicator.pyw Windows tray indicator
windows/gpu-monitor.py    Windows terminal dashboard
windows/install.ps1, uninstall.ps1
windows/tests/            rule tests + astral-guard's case corpus
```

## License

MIT, see [LICENSE](LICENSE). The Windows guard rules and their test corpus are ported from
[astral-hwmon](https://github.com/ksokolowski/astral-hwmon)'s astral-guard (MIT, © Krzysztof Sokołowski).
Not affiliated with ASUS, NVIDIA or REALiX.
