# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Aziz Khalledi
# evaluate() and DEFAULT_LIMITS: Copyright (c) 2026 Krzysztof Sokołowski (astral-hwmon, MIT)
"""Shared code for the Windows port of rtx5090-monitor.

- read_pins():  per-pin 12V-2x6 current/voltage of the ROG Astral, as published by
                HWiNFO64 through its "Report value in Gadget" registry interface
                (HKCU\\Software\\HWiNFO64\\VSB). Free, no 12 h shared-memory limit.
- read_gpu():   nvidia-smi, same query as the Linux indicator.
- evaluate():   the astral-guard rules, ported 1:1 from
                https://github.com/ksokolowski/astral-hwmon guard/guard_eval.c (MIT).

Read-only. Nothing in this module acts on a verdict; astral-guard.py does that.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import subprocess
import time
import winreg
from pathlib import Path

# ---------------------------------------------------------------- paths/config
HOME = Path(os.environ.get("RTX5090_HOME",
                           Path(os.environ.get("LOCALAPPDATA", Path.home())) / "rtx5090-monitor"))
STATE_FILE = HOME / "guard.json"     # written by the guard daemon only
CANCEL_FILE = HOME / "cancel.json"   # written by the indicator only
LOG_FILE = HOME / "guard.log"
CONFIG_FILE = HOME / "config.json"

GUARD_MUTEX = "Local\\rtx5090-astral-guard"
INDICATOR_MUTEX = "Local\\rtx5090-gpu-indicator"

DEFAULT_CONFIG = {
    "check_every_s": 15,          # same cadence as astral-guard.timer on Ubuntu
    "samples": 5,                 # a finding must hold in every sample (rule R6)
    "sample_interval_ms": 1000,   # HWiNFO polls every 2 s by default; set it to 1000 ms
    "auto_shutdown": True,        # CRITICAL -> shutdown /s, like astral-guard-poweroff
    "shutdown_delay_s": 30,       # cancel window
    "hwinfo_key": r"Software\HWiNFO64\VSB",
    "pin_regex": r"(?i)\bpin\s*#?\s*([1-6])\b",   # how a pin number is found in the label
    "sensor_regex": "",           # optional: only accept entries whose sensor name matches
    "comfyui": "",                # optional command for the "Open ComfyUI" menu entry
    "limits": {},                 # optional overrides of DEFAULT_LIMITS
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        user = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(user, dict):
            cfg.update(user)
    except (OSError, ValueError):
        pass
    return cfg


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic: readers never see a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def log(msg):
    HOME.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        if LOG_FILE.stat().st_size > 2_000_000:        # keep ~2 MB
            os.replace(LOG_FILE, LOG_FILE.with_suffix(".log.1"))
    except OSError:
        pass


# ---------------------------------------------------------------- the rules
OK, WARN, CRIT, UNKNOWN, NOTE = 0, 1, 2, 3, -1
LEVEL_NAME = {OK: "OK", WARN: "WARNING", CRIT: "CRITICAL", UNKNOWN: "UNKNOWN", NOTE: "NOTE"}
LEVEL_BY_NAME = {v: k for k, v in LEVEL_NAME.items()}
_SEVERITY = {NOTE: 1, OK: 0, WARN: 2, UNKNOWN: 3, CRIT: 4}

DEFAULT_LIMITS = {
    "pin_warn_ma": 9200,    # ASUS Power Detector+ warning point
    "pin_crit_ma": 9500,    # 12V-2x6 per-pin rating
    "open_pin_ma": 500,     # ASUS PD+ also warns on "or is at 0 amps"
    "open_gate_ma": 10000,
    "ratio_gate_ma": 20000,
    "ratio_note_pct": 85,
    "ratio_warn_pct": 70,   # WireView Pro II's original 30% difference
    "ratio_crit_pct": 60,   # WireView Pro II's field-revised 40%
    "mv_warn": 11400,       # ATX 12 V -5%
    "mv_crit": 11000,       # -8%; no working rail sags this far
}
# Driver plausibility window (driver/astral.h). Outside it a reading is not a measurement.
MV_MIN, MV_MAX, MA_MAX = 6000, 13000, 30000


def severity(level):
    return _SEVERITY.get(level, 3)


def limits_from(cfg=None):
    lim = dict(DEFAULT_LIMITS)
    if cfg:
        lim.update({k: int(v) for k, v in cfg.get("limits", {}).items() if k in lim})
    return lim


def evaluate(samples, lim=None):
    """Port of guard_eval(). samples: list of (mv, ma); mv may be None when HWiNFO
    exposes no per-pin voltages, in which case rule R4 is skipped.
    Returns (level, findings). A finding is reported only if it held in every sample."""
    lim = lim or DEFAULT_LIMITS
    level, findings = OK, []
    n = len(samples)
    if n == 0:
        return level, findings

    def add(lvl, rule, pin, value, detail):
        nonlocal level
        if lvl != NOTE and severity(lvl) > severity(level):
            level = lvl
        findings.append({"rule": rule, "level": LEVEL_NAME[lvl], "pin": pin,
                         "value": value, "detail": detail})

    P = range(6)
    warn_hits, crit_hits, open_hits, worst_ma = [0] * 6, [0] * 6, [0] * 6, [0] * 6
    note_hits = ratio_warn_hits = ratio_crit_hits = mv_warn_hits = mv_crit_hits = 0
    worst_pct = 100
    have_mv = all(mv is not None for mv, _ in samples)
    worst_mv = samples[0][0][0] if have_mv else 0

    for mv, ma in samples:
        for p in P:
            worst_ma[p] = max(worst_ma[p], ma[p])
            if ma[p] >= lim["pin_crit_ma"]:      # inclusive: a rating is a limit
                crit_hits[p] += 1
            if ma[p] >= lim["pin_warn_ma"]:
                warn_hits[p] += 1
        if have_mv:                               # R4, ungated
            lo = min(mv)
            worst_mv = min(worst_mv, lo)
            mv_crit_hits += lo < lim["mv_crit"]
            mv_warn_hits += lo < lim["mv_warn"]
        total = sum(ma)
        if total >= lim["open_gate_ma"]:          # R2 gate
            for p in P:
                if ma[p] < lim["open_pin_ma"]:
                    open_hits[p] += 1
        if total >= lim["ratio_gate_ma"]:         # R3 gate
            lo, hi = min(ma), max(ma)
            if hi > 0:
                worst_pct = min(worst_pct, lo * 100 // hi)
                ratio_crit_hits += lo * 100 < hi * lim["ratio_crit_pct"]
                ratio_warn_hits += lo * 100 < hi * lim["ratio_warn_pct"]
                note_hits += lo * 100 < hi * lim["ratio_note_pct"]

    for p in P:                                   # R2 open pin
        if open_hits[p] == n:
            add(CRIT, "open-pin", p + 1, 0,
                f"pin {p + 1} under {lim['open_pin_ma']} mA while the connector is loaded")
    for p in P:                                   # R1 absolute per-pin current
        if crit_hits[p] == n:
            add(CRIT, "pin-current", p + 1, worst_ma[p],
                f"pin {p + 1} at {worst_ma[p]} mA, at or above the {lim['pin_crit_ma']} mA rating")
        elif warn_hits[p] == n:
            add(WARN, "pin-current", p + 1, worst_ma[p],
                f"pin {p + 1} at {worst_ma[p]} mA, above the {lim['pin_warn_ma']} mA warning point")
    if ratio_crit_hits == n:                      # R3 min/max imbalance
        add(CRIT, "imbalance", 0, worst_pct,
            f"pin currents differ by more than {100 - lim['ratio_crit_pct']}%: min/max {worst_pct}%")
    elif ratio_warn_hits == n:
        add(WARN, "imbalance", 0, worst_pct,
            f"pin currents differ by more than {100 - lim['ratio_warn_pct']}%: min/max {worst_pct}%")
    elif note_hits == n:
        add(NOTE, "imbalance", 0, worst_pct,
            f"pin currents uneven: min/max {worst_pct}% - worth watching")
    if have_mv:                                   # R4 voltage floor
        if mv_crit_hits == n:
            add(CRIT, "voltage", 0, worst_mv, f"lowest pin at {worst_mv} mV, below {lim['mv_crit']} mV")
        elif mv_warn_hits == n:
            add(WARN, "voltage", 0, worst_mv, f"lowest pin at {worst_mv} mV, below {lim['mv_warn']} mV")
    return level, findings


# ---------------------------------------------------------------- HWiNFO
_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _to_float(raw, shown):
    for s in (raw, shown):
        m = _NUM.search(str(s or ""))
        if m:
            return float(m.group(0).replace(",", "."))   # German locale writes 12,104
    return None


def _unit(shown):
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?\s*([A-Za-z]+)\s*$", str(shown or "").strip())
    return m.group(1) if m else ""


def read_vsb(key=None):
    """All entries HWiNFO reports to the Gadget registry key, or None if the key is absent."""
    key = key or os.environ.get("RTX_HWINFO_KEY") or DEFAULT_CONFIG["hwinfo_key"]
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)
    except OSError:
        return None
    vals, i = {}, 0
    with k:
        while True:
            try:
                name, data, _ = winreg.EnumValue(k, i)
            except OSError:
                break
            vals[name] = data
            i += 1
    idx = sorted(int(m.group(1)) for n in vals for m in [re.fullmatch(r"Label(\d+)", n)] if m)
    return [{"index": j, "sensor": str(vals.get(f"Sensor{j}", "")), "label": str(vals.get(f"Label{j}", "")),
             "value": str(vals.get(f"Value{j}", "")), "raw": str(vals.get(f"ValueRaw{j}", ""))}
            for j in idx]


def classify(entries, cfg):
    """-> (ma[6] or None, mv[6] or None, error or None, matched entries)"""
    pin_re = re.compile(cfg.get("pin_regex") or DEFAULT_CONFIG["pin_regex"])
    sensor_re = re.compile(cfg["sensor_regex"]) if cfg.get("sensor_regex") else None
    ma, mv, used = [None] * 6, [None] * 6, []
    for e in entries:
        if sensor_re and not sensor_re.search(e["sensor"]):
            continue
        m = pin_re.search(e["label"])
        if not m:
            continue
        pin = int(m.group(1)) - 1
        unit, val = _unit(e["value"]), _to_float(e["raw"], e["value"])
        if val is None:
            return None, None, f"unreadable value for '{e['label']}'", used
        scale = {"A": 1000, "mA": 1, "V": 1000, "mV": 1}.get(unit)
        if scale is None:
            continue
        target = ma if unit in ("A", "mA") else mv
        if target[pin] is not None:
            return None, None, f"pin {pin + 1} {unit} reported twice - narrow sensor_regex", used
        target[pin] = round(val * scale)
        used.append(e)
    got = sum(v is not None for v in ma)
    if got == 0:
        return None, None, "no pin currents in HWiNFO's Gadget list (see README: Report value in Gadget)", used
    if got < 6:
        # A partial read fails the whole sample: a missing pin must not read as 0 A,
        # which the open-pin rule would report as a dead contact.
        return None, None, f"only {got} of 6 pin currents reported to Gadget", used
    vgot = sum(v is not None for v in mv)
    if 0 < vgot < 6:
        return None, None, f"only {vgot} of 6 pin voltages reported to Gadget", used
    if vgot == 0:
        mv = None
    if any(a < 0 or a > MA_MAX for a in ma):
        return None, None, f"implausible pin current {ma}", used
    if mv and any(v < MV_MIN or v > MV_MAX for v in mv):
        return None, None, f"implausible pin voltage {mv}", used
    return ma, mv, None, used


def read_pins(cfg=None):
    """-> (ma[6], mv[6] or None, error). ma is None on any failure."""
    cfg = cfg or load_config()
    fake = os.environ.get("RTX_FAKE_SENSORS")          # test hook: JSON {"ma": [...], "mv": [...]}
    if fake:
        d = read_json(fake)
        if not d:
            return None, None, "fake sensor file unreadable"
        return d["ma"], d.get("mv"), None
    if not process_running("HWiNFO64.exe") and not process_running("HWiNFO.exe"):
        return None, None, "HWiNFO64 is not running"
    entries = read_vsb(os.environ.get("RTX_HWINFO_KEY") or cfg.get("hwinfo_key"))
    if entries is None:
        return None, None, "HWiNFO Gadget reporting is off (Settings > HWiNFO Gadget)"
    ma, mv, err, _ = classify(entries, cfg)
    return ma, mv, err


def sample_run(cfg, n=None, interval_ms=None):
    """n samples -> (level, findings, last (ma, mv) or None, error)."""
    n = n or int(cfg["samples"])
    interval = (interval_ms if interval_ms is not None else int(cfg["sample_interval_ms"])) / 1000
    samples, last = [], None
    for i in range(n):
        ma, mv, err = read_pins(cfg)
        if err:
            return UNKNOWN, [], last, err
        samples.append((mv, ma))
        last = (ma, mv)
        if i + 1 < n:
            time.sleep(interval)
    level, findings = evaluate(samples, limits_from(cfg))
    return level, findings, last, None


# ---------------------------------------------------------------- nvidia-smi
NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW: no console flash under pythonw
THROTTLE_BITS = {0x4: "power cap", 0x8: "HW slowdown", 0x20: "SW thermal",
                 0x40: "HW thermal", 0x80: "power brake"}
GPU_QUERY = ("temperature.gpu,power.draw,power.limit,utilization.gpu,memory.used,memory.total,"
             "fan.speed,clocks.sm,clocks_event_reasons.active")


def read_gpu():
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout.strip().split("\n")[0]
        t, p, pl, u, mu, mt, fan, clk, reasons = [x.strip() for x in out.split(",")]
        r = int(reasons, 16)
        return dict(temp=int(t), power=float(p), limit=float(pl), util=int(u),
                    mem_used=int(mu), mem_total=int(mt), fan=fan, clock=int(clk),
                    throttle=", ".join(n for b, n in THROTTLE_BITS.items() if r & b) or "none")
    except Exception:
        return None


# ---------------------------------------------------------------- win32 helpers
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wt.HANDLE
_k32.OpenMutexW.restype = wt.HANDLE
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
SYNCHRONIZE, ERROR_ALREADY_EXISTS = 0x00100000, 183


def single_instance(name):
    """Hold a named mutex for the life of the process. False if another instance has it."""
    h = _k32.CreateMutexW(None, False, name)
    if not h or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    single_instance.handles.append(h)   # keep it alive
    return True


single_instance.handles = []


def mutex_exists(name):
    h = _k32.OpenMutexW(SYNCHRONIZE, False, name)
    if h:
        _k32.CloseHandle(h)
        return True
    return False


class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def processes():
    """{pid: exe name} for every process, elevated ones included (HWiNFO runs elevated)."""
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    if not snap or snap == wt.HANDLE(-1).value:
        return out
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(e)
        ok = _k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[e.th32ProcessID] = e.szExeFile
            ok = _k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        _k32.CloseHandle(snap)
    return out


def process_running(exe):
    exe = exe.lower()
    return any(n.lower() == exe for n in processes().values())


def shutdown_state():
    """What the indicator shows: (pending, seconds_left)."""
    st = read_json(STATE_FILE, {}) or {}
    cancel = read_json(CANCEL_FILE, {}) or {}
    issued, at = st.get("shutdown_issued", 0), st.get("shutdown_at", 0)
    if issued and at > time.time() and cancel.get("cancelled_at", 0) < issued:
        return True, int(at - time.time())
    return False, 0
