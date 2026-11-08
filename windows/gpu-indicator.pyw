"""System-tray indicator for the ROG Astral RTX 5090 (Windows port of bin/gpu-indicator).

Icon:     worst pin current, coloured by the guard verdict (green/amber/red, grey = unknown)
Tooltip:  <max pin current>  <GPU temp>  <board power>
Menu:     verdict + findings, per-pin current/voltage, GPU stats, shortcuts,
          cancel pending shutdown, monitoring on/off, exit.
A desktop notification pops up whenever the verdict gets worse.

Reads only: HWiNFO64 Gadget values, nvidia-smi, and the guard daemon's state file.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import astral_core as core  # noqa: E402

REFRESH_S = 2        # pins + GPU
GUARD_EVERY_S = 6    # full rule check (5 samples)
LEVEL_RANK = {"OK": 0, "UNKNOWN": 1, "WARNING": 2, "CRITICAL": 3}
COLOR = {"OK": (46, 157, 70), "WARNING": (224, 160, 0), "CRITICAL": (211, 47, 47),
         "UNKNOWN": (110, 110, 110), "OFF": (60, 60, 60)}
PYW = Path(sys.executable).with_name("pythonw.exe")
PY = Path(sys.executable).with_name("python.exe")
DETACHED = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_icon(text, color, ring=None):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 63, 63), radius=12, fill=color + (255,),
                        outline=(ring or color) + (255,), width=6 if ring else 1)
    for size in range(44, 12, -2):          # biggest text that fits
        f = _font(size)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        if r - l <= 56:
            break
    d.text((32 - (r + l) / 2, 32 - (b + t) / 2), text, font=f, fill=(255, 255, 255, 255))
    return img


def launch(cmd):
    subprocess.Popen(cmd, creationflags=DETACHED | core.NO_WINDOW, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_console(title, args):
    """New console window running args (Windows Terminal if present)."""
    wt = shutil.which("wt.exe")
    if wt:
        subprocess.Popen([wt, "-w", "new", "--title", title] + args)
    else:
        subprocess.Popen(["cmd", "/c", "start", title] + args)


class Indicator:
    def __init__(self):
        self.cfg = core.load_config()
        self.lim = core.limits_from(self.cfg)
        self.level, self.findings, self.err = "UNKNOWN", [], None
        self.monitoring = None
        self.pending, self.left = False, 0
        self.t_guard, self.t_find = "12V-2x6 guard: ...", ""
        self.t_pins = [f"Pin {i}: ..." for i in range(1, 7)]
        self.t_total = ""
        self.t_gpu = ["", "", "", ""]
        I, S = pystray.MenuItem, pystray.Menu.SEPARATOR
        info = lambda f: I(lambda _: f(), None, enabled=False)   # display-only row
        self.icon = pystray.Icon("rtx5090-guard", make_icon("..", COLOR["UNKNOWN"]), "RTX 5090 monitor",
                                 pystray.Menu(
            I(lambda _: f"STOP  CANCEL PENDING SHUTDOWN ({self.left} s)", self.on_cancel,
              visible=lambda _: self.pending),
            info(lambda: self.t_guard), info(lambda: self.t_find), S,
            *[info(lambda k=k: self.t_pins[k]) for k in range(6)], info(lambda: self.t_total), S,
            *[info(lambda k=k: self.t_gpu[k]) for k in range(4)], S,
            I("Open GPU Monitor", self.on_monitor, default=True),
            I("Open ComfyUI", lambda: launch(self.cfg["comfyui"]), visible=lambda _: bool(self.cfg.get("comfyui"))),
            I("Open HWiNFO64", self.on_hwinfo),
            I("Guard log", self.on_log), S,
            I(lambda _: "Turn monitoring off (until next sign-in)" if self.monitoring
              else "(!) Monitoring is OFF - turn it on", self.on_toggle), S,
            I("Exit indicator", lambda: self.icon.stop())))

    # ---- shortcuts ----
    def on_monitor(self):
        open_console("GPU Monitor", [str(PY), str(HERE / "gpu-monitor.py")])

    def on_log(self):
        core.LOG_FILE.touch(exist_ok=True)
        open_console("astral-guard log", ["powershell", "-NoProfile", "-NoExit", "-Command",
                                          f"Get-Content -Wait -Tail 50 -LiteralPath '{core.LOG_FILE}'"])

    def on_hwinfo(self):
        for p in (r"C:\Program Files\HWiNFO64\HWiNFO64.exe", r"C:\Program Files (x86)\HWiNFO64\HWiNFO64.exe"):
            if os.path.exists(p):
                os.startfile(p)   # elevates via its manifest
                return
        self.notify("HWiNFO64 not found", "Install it: winget install REALiX.HWiNFO")

    def notify(self, title, body):
        try:
            self.icon.notify(body[:255], title[:63])
        except Exception:
            pass

    # ---- guard control ----
    def on_cancel(self):
        r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True, creationflags=core.NO_WINDOW)
        core.write_json(core.CANCEL_FILE, {"cancelled_at": time.time(), "shutdown_a_exit": r.returncode})
        core.log(f"indicator: cancel pressed, shutdown /a exit {r.returncode}")
        if r.returncode in (0, 1116):   # 1116 = no shutdown in progress (dry run / already aborted)
            self.notify("Shutdown cancelled", "The pending shutdown was stopped. Check the cable/connector "
                        "before running heavy loads again.")
        else:
            self.notify("Could not cancel shutdown", "Run in a terminal: shutdown /a")
        self.poll_units()

    def on_toggle(self):
        if self.monitoring:
            pid = (core.read_json(core.STATE_FILE, {}) or {}).get("pid")
            name = core.processes().get(pid, "").lower() if pid else ""
            if name.startswith("python"):
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                               creationflags=core.NO_WINDOW)
            time.sleep(0.5)
            if core.mutex_exists(core.GUARD_MUTEX):
                self.notify("Could not change monitoring", "The guard did not stop.")
            else:
                core.log("indicator: monitoring turned OFF (until next sign-in)")
                self.notify("12V-2x6 monitoring OFF", "Background checks and auto-shutdown are paused until "
                            "you turn them back on or sign in again.")
        else:
            launch([str(PYW), str(HERE / "astral-guard.py"), "--daemon"])
            for _ in range(20):
                if core.mutex_exists(core.GUARD_MUTEX):
                    break
                time.sleep(0.1)
            core.log("indicator: monitoring turned ON")
            self.notify("12V-2x6 monitoring ON",
                        f"Checks every {self.cfg['check_every_s']} s; auto-shutdown "
                        f"{'armed' if self.cfg['auto_shutdown'] else 'disabled in config.json'}.")
        self.poll_units()

    def poll_units(self):
        self.monitoring = core.mutex_exists(core.GUARD_MUTEX)
        pending, self.left = core.shutdown_state()
        if pending and not self.pending:
            self.notify("RTX 5090: SHUTDOWN PENDING",
                        "Critical connector verdict. Tray icon > Cancel pending shutdown to abort.")
        self.pending = pending

    # ---- rule check (thread: it samples for ~5 s) ----
    def guard_loop(self):
        while True:
            self.cfg = core.load_config()
            self.lim = core.limits_from(self.cfg)
            lvl, findings, _, err = core.sample_run(self.cfg)
            self.guard_done(core.LEVEL_NAME[lvl], findings, err)
            time.sleep(GUARD_EVERY_S)

    def guard_done(self, level, findings, err):
        prev, self.level, self.findings, self.err = self.level, level, findings, err
        if LEVEL_RANK.get(level, 1) > LEVEL_RANK.get(prev, 1) and level in ("WARNING", "CRITICAL"):
            self.notify(f"RTX 5090 connector: {level}", "; ".join(f["detail"] for f in findings) or level)
        self.t_guard = f"12V-2x6 guard: {level}"
        self.t_find = ("; ".join(f["detail"] for f in findings)[:120] if findings
                       else "No findings - connector looks healthy" if level == "OK"
                       else f"Sensor not readable: {err}" if err else "")

    # ---- fast refresh ----
    def refresh_loop(self):
        while True:
            try:
                self.refresh()
            except Exception as e:   # never let the tray die on a bad frame
                core.log(f"indicator refresh error: {e!r}")
            time.sleep(REFRESH_S)

    def refresh(self):
        self.poll_units()
        ma, mv, err = core.read_pins(self.cfg)
        gpu = core.read_gpu()
        warn_a, crit_a = self.lim["pin_warn_ma"] / 1000, self.lim["pin_crit_ma"] / 1000
        parts, icon_text = [], "--"
        if ma:
            amps = [a / 1000 for a in ma]
            volts = [v / 1000 for v in mv] if mv else [None] * 6
            peak = max(amps)
            parts.append(f"{peak:.1f}A")
            icon_text = f"{peak:.1f}" if peak < 10 else f"{peak:.0f}"
            for i, (a, v) in enumerate(zip(amps, volts)):
                mark = "   [CRIT]" if a >= crit_a else "   [WARN]" if a >= warn_a else ""
                vs = f"{v:5.2f} V" if v is not None else "  -- V"
                self.t_pins[i] = f"Pin {i + 1}:   {a:5.2f} A    {vs}{mark}"
            total_w = sum(a * (v if v is not None else 12.0) for a, v in zip(amps, volts))
            spread = (min(amps) / peak * 100) if peak >= 1 else 100
            self.t_total = (f"Connector: {'' if mv else '~'}{total_w:.0f} W   balance {spread:.0f}%   "
                            f"(warn {warn_a:g} A / crit {crit_a:g} A per pin)")
        else:
            self.t_pins = ["-"] * 6
            self.t_total = f"Per-pin sensor not available: {err}"
            parts.append("-A")
        if gpu:
            parts += [f"{gpu['temp']}°C", f"{gpu['power']:.0f}W"]
            self.t_gpu = [f"GPU: {gpu['temp']} °C   {gpu['power']:.0f} / {gpu['limit']:.0f} W   load {gpu['util']}%",
                          f"VRAM: {gpu['mem_used'] / 1024:.1f} / {gpu['mem_total'] / 1024:.1f} GB",
                          f"Core clock: {gpu['clock']} MHz   fan {gpu['fan']}%",
                          f"Throttling: {gpu['throttle']}"]
        level = self.level
        if self.pending:
            parts.insert(0, f"SHUTDOWN in {self.left}s")
            img = make_icon("SD", COLOR["CRITICAL"], ring=(255, 255, 255))
        elif self.monitoring is False:
            parts.insert(0, "MON OFF")
            img = make_icon(icon_text, COLOR["OFF"], ring=COLOR.get(level))
        else:
            img = make_icon(icon_text, COLOR.get(level, COLOR["UNKNOWN"]))
        self.icon.icon = img
        self.icon.title = ("RTX 5090  " + "  ".join(parts) + f"  [{level}]")[:127]
        self.icon.update_menu()

    def run(self):
        def setup(icon):
            icon.visible = True
            threading.Thread(target=self.guard_loop, daemon=True).start()
            threading.Thread(target=self.refresh_loop, daemon=True).start()
        self.icon.run(setup)


if __name__ == "__main__":
    if core.single_instance(core.INDICATOR_MUTEX):
        Indicator().run()
