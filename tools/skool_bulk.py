"""Run a brain's Skool crawl phases one after another, unattended (one Skool process at a time).

Usage: python -I tools/skool_bulk.py --phases lessons,attachments,recache,expert,replied
         --brain <brain> [--replied-since YYYY-MM-DD] [--recache-until YYYY-MM-DD] [--cooldown 1800] [--whisper auto|on|off]

Each phase is one of the incremental crawlers; re-running a finished phase is cheap (it skips what's in state).
- A phase that stops on RateLimited (Skool's WAF) is re-run after --cooldown seconds, up to 8 times.
- NotLoggedIn (or any crash) stops the whole run with status NEEDS_USER / FAILED.
- `lessons` adds --whisper with `--whisper on`, never with `off`, and by default (`auto`) only when the GPU looks idle
  (Loom videos stay `needs_whisper` otherwise). Desktop apps can keep `auto` from firing on an idle card, so pass `on`
  when you know the GPU is free.
Progress: <scratch>/logs/bulk-<phase>.log (crawler output) and <scratch>/logs/bulk_status.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I drops the script directory
import brainlib
from skool_session import configure, scratch_dir

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import time

sys.stdout.reconfigure(encoding="utf-8")
PY = [sys.executable, "-X", "utf8", "-I"]


def gpu_idle() -> bool:
    program = shutil.which("nvidia-smi")
    if not program:
        return False
    try:
        out = subprocess.run([program, "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, encoding="utf-8", timeout=20).stdout
        util, mem = (int(x) for x in out.strip().splitlines()[0].split(","))
        return util < 20 and mem < 6000
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    brainlib.add_brain_arg(ap)
    ap.add_argument("--phases", required=True)
    ap.add_argument("--replied-since", default=None)
    ap.add_argument("--recache-until", default=None)
    ap.add_argument("--cooldown", type=int, default=1800)
    ap.add_argument("--whisper", choices=["auto", "on", "off"], default="auto",
                    help="transcribe Loom lessons: auto = only if the GPU looks idle")
    args = ap.parse_args()
    brain, config = configure(args)
    ROOT = brainlib.workspace(brain)
    logs = scratch_dir(brain, "logs")
    logs.mkdir(parents=True, exist_ok=True)
    status_p = logs / "bulk_status.json"
    status = {"started": dt.datetime.now().isoformat(timespec="seconds"), "phases": {}, "state": "running"}

    def save(**kw):
        status.update(kw)
        status_p.write_text(json.dumps(status, indent=1), encoding="utf-8")

    def use_whisper():
        on = args.whisper == "on" or (args.whisper == "auto" and gpu_idle())
        print(f"lessons: whisper {'on' if on else 'off'} (--whisper {args.whisper})", flush=True)
        return on

    t = Path(__file__).resolve().parent
    common = ["--brain", str(brain)]
    cmds = {
        "lessons": lambda: [*PY, str(t / "skool_classroom_crawl.py"), *common] + (["--whisper"] if use_whisper() else []),
        "attachments": lambda: [*PY, str(t / "skool_attachments.py"), *common],
        "recache": lambda: [*PY, str(t / "skool_feed_index.py"), "--mode", "recache", "--until", args.recache_until,
                            *common],
        "expert": lambda: [*PY, str(t / "skool_thread_crawl.py"), *common, "--tier", "expert"],
        "replied": lambda: [*PY, str(t / "skool_thread_crawl.py"), *common, "--tier", "replied"]
                           + (["--since", args.replied_since] if args.replied_since else []),
    }
    for phase in args.phases.split(","):
        if phase not in cmds:
            sys.exit(f"unknown phase {phase}")
        if phase == "recache" and not args.recache_until:
            sys.exit("recache needs --recache-until")
    save()
    for phase in args.phases.split(","):
        for attempt in range(1, 10):
            cmd = cmds[phase]()
            started = dt.datetime.now().isoformat(timespec="seconds")
            status["phases"][phase] = {"attempt": attempt, "started": started, "state": "running", "cmd": " ".join(cmd[2:])}
            save(current=phase)
            print(f"[{started}] {phase} attempt {attempt}: {' '.join(cmd[2:])}", flush=True)
            with open(logs / f"bulk-{phase}.log", "a", encoding="utf-8") as log:
                log.write(f"\n=== {started} attempt {attempt}\n")
                log.flush()
                proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
                chunks = []
                for line in proc.stdout:  # stream so the log shows live progress
                    chunks.append(line)
                    log.write(line)
                    log.flush()
                proc.wait()
            out = "".join(chunks)
            tail = [ln for ln in out.splitlines() if ln.strip()][-3:]
            status["phases"][phase].update({"ended": dt.datetime.now().isoformat(timespec="seconds"), "tail": tail,
                                            "errors": out.count(": ERROR ")})
            if "NotLoggedIn" in out:
                status["phases"][phase]["state"] = "needs_user"
                save(state="NEEDS_USER", note=f"Skool session expired: log in again in the configured Chrome window (port {config.get('cdp_port')}, profile {config.get('profile', 'unspecified')}), then re-run")
                print("NEEDS_USER: Skool login needed", flush=True)
                return 2
            if proc.returncode != 0:
                status["phases"][phase]["state"] = "failed"
                save(state="FAILED", note=f"{phase} exited {proc.returncode}; see bulk-{phase}.log")
                print(f"FAILED: {phase} exit {proc.returncode}", flush=True)
                return 1
            if "RateLimited" in out:
                status["phases"][phase]["state"] = "cooldown"
                save(note=f"{phase} rate-limited; cooling down {args.cooldown}s")
                print(f"{phase}: rate-limited, cooling down {args.cooldown}s", flush=True)
                time.sleep(args.cooldown)
                continue
            status["phases"][phase]["state"] = "done"
            save()
            print(f"{phase}: done ({tail[-1] if tail else ''})", flush=True)
            break
        else:
            save(state="FAILED", note=f"{phase} still rate-limited after 9 attempts")
            return 1
    save(state="DONE", current=None, finished=dt.datetime.now().isoformat(timespec="seconds"))
    print("all phases done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
