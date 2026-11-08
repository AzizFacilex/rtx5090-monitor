"""Live RTX 5090 dashboard: 12V-2x6 per-pin readings + guard verdict + GPU thermals/power.
Windows port of bin/gpu-monitor. Ctrl+C to quit."""
import os
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astral_core as core  # noqa: E402

REFRESH_S = 2
GPU_COLS = ("temperature.gpu,power.draw,power.limit,clocks.sm,clocks.mem,fan.speed,"
            "utilization.gpu,memory.used,memory.total,clocks_event_reasons.active")
RED, YEL, GRN, DIM, RST = "\033[31;1m", "\033[33;1m", "\033[32m", "\033[2m", "\033[0m"
LVL_COLOR = {"OK": GRN, "WARNING": YEL, "CRITICAL": RED, "UNKNOWN": DIM}


def gpu_table():
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={GPU_COLS}", "--format=csv"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
    except Exception as e:
        return [f"(nvidia-smi failed: {e})"]
    rows = [[c.strip() for c in line.split(",")] for line in out]
    widths = [max(len(r[i]) for r in rows if i < len(r)) for i in range(len(rows[0]))]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]


def main():
    os.system("")                         # enable ANSI escapes in conhost
    cfg = core.load_config()
    lim = core.limits_from(cfg)
    window = deque(maxlen=int(cfg["samples"]))   # rolling: last N refreshes
    while True:
        ma, mv, err = core.read_pins(cfg)
        if err:
            window.clear()
        else:
            window.append((mv, ma))
        lines = [f"=== 12V-2x6 connector  (warn >= {lim['pin_warn_ma'] / 1000:g} A/pin, "
                 f"critical >= {lim['pin_crit_ma'] / 1000:g} A) ==="]
        if err:
            lines.append(f"{DIM}astral-guard: UNKNOWN - {err}{RST}")
        else:
            lvl, findings = core.evaluate(list(window), lim)
            name = core.LEVEL_NAME[lvl]
            filled = f"{len(window)}/{window.maxlen} samples"
            lines.append(f"astral-guard: {LVL_COLOR[name]}{name}{RST}  {DIM}({filled}, rolling){RST}")
            lines += [f"  {f['level']:<8} {f['detail']}" for f in findings]
            for i in range(6):
                a = ma[i] / 1000
                col = RED if ma[i] >= lim["pin_crit_ma"] else YEL if ma[i] >= lim["pin_warn_ma"] else ""
                v = f"{mv[i] / 1000:6.3f} V" if mv else "    -- V"
                bar = "#" * int(min(a, 10) * 4)
                lines.append(f"  Pin {i + 1}  {col}{a:6.2f} A{RST}  {v}  {col}{bar}{RST}")
            peak = max(ma)
            total_w = sum(a * (v if mv else 12000) for a, v in zip(ma, mv or [0] * 6)) / 1e6
            lines.append(f"  total {sum(ma) / 1000:.2f} A  ~{total_w:.0f} W   "
                         f"balance {min(ma) * 100 // peak if peak >= 1000 else 100}%")
        st = core.read_json(core.STATE_FILE, {}) or {}
        mon = core.mutex_exists(core.GUARD_MUTEX)
        pending, left = core.shutdown_state()
        lines.append(f"  background guard: {'ON' if mon else RED + 'OFF' + RST}"
                     + (f"  {RED}SHUTDOWN IN {left} s - run: shutdown /a{RST}" if pending else "")
                     + (f"  {DIM}(last verdict {st.get('level')}){RST}" if mon and st else ""))
        lines += ["", "=== GPU ==="] + gpu_table()
        sys.stdout.write("\033[H\033[2J" + "\n".join(lines) + "\n")
        sys.stdout.flush()
        time.sleep(REFRESH_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
