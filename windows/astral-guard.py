"""astral-guard for Windows: the 12V-2x6 rule check, fed by HWiNFO64.

  astral-guard.py                 one check, human-readable, exit 0/1/2/3 = OK/WARNING/CRITICAL/UNKNOWN
  astral-guard.py --json          same, the JSON shape of astral-guard --json
  astral-guard.py --list-sensors  what HWiNFO reports to Gadget, and which entries became pins
  astral-guard.py --daemon        check every 15 s; on CRITICAL run `shutdown /s /t 30`
                                  (the Windows stand-in for astral-guard.timer + astral-guard-poweroff)
  add --dry-run to the daemon to log the shutdown instead of doing it.

Only a CRITICAL verdict from the rules can shut the machine down. UNKNOWN (HWiNFO closed,
sensor missing, implausible reading) never does: it fails towards staying powered on.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astral_core as core  # noqa: E402


def report(level, findings, cfg, err):
    return [{"chip": "HWiNFO64 Gadget (HKCU\\" + cfg["hwinfo_key"] + ")",
             "update_interval_ms": int(cfg["sample_interval_ms"]),
             "level": core.LEVEL_NAME[level], "exit_code": level,
             "findings": findings, "error": err, "limits": core.limits_from(cfg)}]


def one_shot(args, cfg):
    level, findings, last, err = core.sample_run(cfg, args.samples, args.interval)
    if args.json:
        print(json.dumps(report(level, findings, cfg, err), indent=2))
    else:
        print(f"astral-guard: {core.LEVEL_NAME[level]}" + (f" - {err}" if err else ""))
        for f in findings:
            print(f"  {f['level']:<8} {f['rule']:<12} {f['detail']}")
        if last:
            ma, mv = last
            print("  pins (A): " + "  ".join(f"{a / 1000:5.2f}" for a in ma))
            if mv:
                print("  pins (V): " + "  ".join(f"{v / 1000:5.2f}" for v in mv))
    return level


def list_sensors(cfg):
    entries = core.read_vsb(cfg["hwinfo_key"])
    print("HWiNFO64 running:", core.process_running("HWiNFO64.exe"))
    if entries is None:
        print(f"HKCU\\{cfg['hwinfo_key']} not found: enable Settings > HWiNFO Gadget > "
              "'Enable reporting to Gadget' and tick 'Report value in Gadget' for each pin.")
        return core.UNKNOWN
    ma, mv, err, used = core.classify(entries, cfg)
    used_ix = {e["index"] for e in used}
    for e in entries:
        mark = "PIN" if e["index"] in used_ix else "   "
        print(f" {mark} [{e['index']:>3}] {e['sensor'][:34]:<34} {e['label'][:34]:<34} {e['value']}")
    print("\nresult:", err or f"currents mA {ma}, voltages mV {mv or 'not reported (rule R4 off)'}")
    return core.UNKNOWN if err else core.OK


def shutdown_now(findings, cfg, dry_run):
    delay = int(cfg["shutdown_delay_s"])
    why = "; ".join(f["detail"] for f in findings if f["level"] == "CRITICAL")[:300]
    msg = (f"astral-guard: CRITICAL 12V-2x6 verdict ({why}). Shutting down in {delay} s to protect "
           "the connector. Cancel from the RTX 5090 tray icon or run: shutdown /a")
    if dry_run:
        core.log(f"DRY RUN: would run shutdown /s /t {delay}  -- {why}")
        return True
    r = subprocess.run(["shutdown", "/s", "/t", str(delay), "/c", msg],
                       capture_output=True, text=True, creationflags=core.NO_WINDOW)
    if r.returncode != 0:
        core.log(f"shutdown /s FAILED ({r.returncode}): {(r.stderr or r.stdout).strip()}")
        return False
    core.log(f"CRITICAL -> shutdown /s /t {delay} issued: {why}")
    return True


def daemon(cfg, dry_run):
    if not core.single_instance(core.GUARD_MUTEX):
        return 0                                   # already running
    state = {"pid": os.getpid(), "started": time.time(), "dry_run": dry_run,
             "level": "UNKNOWN", "findings": [], "error": None, "last_check": 0,
             "shutdown_issued": 0, "shutdown_at": 0}
    core.write_json(core.STATE_FILE, state)
    core.log(f"guard started (pid {os.getpid()}, every {cfg['check_every_s']} s, "
             f"{cfg['samples']} x {cfg['sample_interval_ms']} ms, auto_shutdown={cfg['auto_shutdown']}"
             f"{', DRY RUN' if dry_run else ''})")
    prev = None
    while True:
        t0 = time.time()
        cfg = core.load_config()                   # pick up edits without a restart
        level, findings, _, err = core.sample_run(cfg)
        name = core.LEVEL_NAME[level]
        if (name, err) != prev:
            core.log(f"verdict {name}" + (f" - {err}" if err else "") +
                     "".join(f"\n    {f['level']}: {f['detail']}" for f in findings))
            prev = (name, err)
        state.update(level=name, findings=findings, error=err, last_check=time.time(),
                     limits=core.limits_from(cfg))
        pending, _ = core.shutdown_state()
        if level == core.CRIT and cfg["auto_shutdown"] and not pending:
            if shutdown_now(findings, cfg, dry_run):
                state.update(shutdown_issued=time.time(),
                             shutdown_at=time.time() + int(cfg["shutdown_delay_s"]))
        core.write_json(core.STATE_FILE, state)
        time.sleep(max(1.0, float(cfg["check_every_s"]) - (time.time() - t0)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--samples", type=int)
    ap.add_argument("--interval", type=int, help="ms between samples")
    ap.add_argument("--list-sensors", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = core.load_config()
    if a.samples is not None and not 1 <= a.samples <= 32:
        ap.error("--samples must be 1..32")
    if a.daemon:
        try:
            return daemon(cfg, a.dry_run)
        except Exception as e:                     # make a crash visible in the log
            core.log(f"guard crashed: {e!r}")
            raise
    if a.list_sensors:
        return list_sensors(cfg)
    return one_shot(a, cfg)


if __name__ == "__main__":
    sys.exit(main())
