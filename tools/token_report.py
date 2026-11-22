"""Report local agent usage without exposing message text.

Usage: token_report.py --workspace PATH [--since YYYY-MM-DD] [--json]
Input-equivalent uses Anthropic's relative price ratios as a rough common unit:
input + cache-read * 0.1 + cache-write * 1.25 + output * 5.
Codex input includes cached input, which is subtracted before applying ratios.
T3 end-of-turn context snapshots are not token totals and are excluded from costs.
"""
import argparse
import contextlib
import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
import sys


def events(path):
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield value
                except (ValueError, TypeError):
                    continue
    except OSError:
        return


def row(source, session):
    return dict(source=source, session=str(session), start="", model="unknown", turns=0,
                max_context=0, mean_context=0, input_tokens=0, cache_read_tokens=0,
                cache_write_tokens=0, output_tokens=0, input_equivalent=0,
                trigger_equivalent=dict(user=0, worker=0, scheduled=0))


def finish(result, contexts):
    result["turns"] = len(contexts)
    result["max_context"] = max(contexts, default=0)
    result["mean_context"] = sum(contexts) / len(contexts) if contexts else 0
    return result


def claude(path, scheduled):
    result = row("claude-sub" if "subagents" in path.parts else "claude", path.stem)
    contexts, seen, trigger = [], set(), "user"
    for event in events(path):
        result["start"] = result["start"] or str(event.get("timestamp", ""))[:10]
        message = event.get("message") or {}
        if event.get("type") == "user" and not event.get("isMeta"):
            content = message.get("content", "")
            text = content if isinstance(content, str) else "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
            if text.strip():
                trigger = ("worker" if text.startswith(("<task-notification", "Delegated task"))
                           else "scheduled" if scheduled.search(text.splitlines()[0]) else "user")
        usage = message.get("usage")
        if event.get("type") != "assistant" or not usage:
            continue
        identity = message.get("id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result["model"] = message.get("model", "unknown")
        values = [usage.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")]
        for key, value in zip(("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"), values):
            result[key] += value
        cost = values[0] + values[1] * .1 + values[2] * 1.25 + values[3] * 5
        result["input_equivalent"] += cost
        result["trigger_equivalent"][trigger] += cost
        contexts.append(sum(values[:3]))
    return finish(result, contexts)


def inside(cwd, workspace):
    try:
        return pathlib.Path(cwd).expanduser().resolve().is_relative_to(workspace)
    except (OSError, ValueError, TypeError):
        return False


def codex(path, workspace):
    result, contexts, belongs, total = row("codex", path.stem), [], False, {}
    for event in events(path):
        payload = event.get("payload") or {}
        if event.get("type") == "session_meta":
            belongs = inside(payload.get("cwd"), workspace)
            result["start"] = str(payload.get("timestamp") or event.get("timestamp", ""))[:10]
        if event.get("type") == "turn_context":
            result["model"] = payload.get("model", "unknown")
        if payload.get("type") == "token_count" and payload.get("info"):
            info = payload["info"]
            if info.get("total_token_usage"):
                total = info["total_token_usage"]
            last = info.get("last_token_usage") or {}
            if "input_tokens" in last:
                contexts.append(last["input_tokens"])
    if not belongs:
        return None
    cached = total.get("cached_input_tokens", 0) or 0
    result.update(input_tokens=max(0, (total.get("input_tokens", 0) or 0) - cached),
                  cache_read_tokens=cached, output_tokens=total.get("output_tokens", 0) or 0)
    result["input_equivalent"] = result["input_tokens"] + cached * .1 + result["output_tokens"] * 5
    return finish(result, contexts)


def t3_rows(path, workspace, since, notes):
    grouped = {}
    try:
        with contextlib.closing(sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            query = """SELECT t.thread_id, t.started_at, t.payload_json, p.workspace_root, h.title
                FROM orchestration_v2_projection_provider_turns t
                JOIN orchestration_v2_projection_threads h ON h.thread_id=t.thread_id
                JOIN projection_projects p ON p.project_id=h.project_id"""
            for identity, started, payload, root, title in db.execute(query):
                if not root or pathlib.Path(root).resolve() != workspace or (since and str(started)[:10] < since):
                    continue
                try:
                    data = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                result, contexts = grouped.setdefault(identity, (row("t3", title or identity), []))
                date = str(started)[:10]
                result["start"] = min(result["start"] or date, date)
                result["model"] = data.get("model", "unknown")
                usage = data.get("tokenUsage") or {}
                contexts.append(usage.get("usedTokens", usage.get("inputTokens", 0)) or 0)
    except sqlite3.Error as exc:
        notes.append("T3 unavailable: " + str(exc).splitlines()[0])
    return [finish(r, c) for r, c in grouped.values()]


def report(args):
    workspace = pathlib.Path(args.workspace).expanduser().resolve()
    directories = args.claude_dir
    if directories is None:
        directories = [pathlib.Path.home() / ".claude", *pathlib.Path.home().glob(".claude-*")]
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            directories.append(pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]))
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(workspace)).casefold()
    rows, notes, seen = [], [], set()
    for directory in directories:
        projects = pathlib.Path(directory).expanduser() / "projects"
        if not projects.is_dir():
            continue
        for project in projects.iterdir():
            if project.name.casefold() != slug:
                continue
            for path in [*project.glob("*.jsonl"), *project.glob("*/subagents/*.jsonl")]:
                if path.resolve() not in seen:
                    seen.add(path.resolve())
                    rows.append(claude(path, re.compile(args.trigger_scheduled)))
    home = pathlib.Path(args.codex_dir or os.environ.get("CODEX_HOME", pathlib.Path.home() / ".codex")).expanduser()
    for path in (home / "sessions").rglob("rollout-*.jsonl"):
        result = codex(path, workspace)
        if result:
            rows.append(result)
    rows = [r for r in rows if r["turns"] and (not args.since or r["start"] >= args.since)]
    if args.t3_db:
        rows.extend(t3_rows(args.t3_db, workspace, args.since, notes))
        notes.append("T3 rows are end-of-turn context snapshots only; no token totals or cost are inferred.")
    for r in rows:
        r["warning"] = r["max_context"] > args.ctx_warn
    t3 = sorted((r for r in rows if r["source"] == "t3"), key=lambda r: r["turns"] * r["mean_context"], reverse=True)
    rows = sorted((r for r in rows if r["source"] != "t3"), key=lambda r: (r["input_equivalent"], r["max_context"]), reverse=True)
    keys = ("turns", "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "input_equivalent")
    totals = {key: sum(r[key] for r in rows) for key in keys}
    triggers = {key: sum(r["trigger_equivalent"][key] for r in rows) for key in ("user", "worker", "scheduled")}
    denominator = sum(triggers.values())
    return dict(sessions=rows[:args.top], total_sessions=len(rows), t3_threads=t3[:args.top], total_t3_threads=len(t3), totals=totals,
                trigger_equivalent=triggers, trigger_shares={k: v / denominator if denominator else 0 for k, v in triggers.items()}, notes=notes)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--since", type=lambda s: dt.date.fromisoformat(s).isoformat())
    ap.add_argument("--claude-dir", action="append")
    ap.add_argument("--codex-dir")
    ap.add_argument("--t3-db")
    ap.add_argument("--ctx-warn", type=int, default=200000)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--trigger-scheduled", default="(?i)reminder|scheduled")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.top < 1:
        ap.error("--top must be positive")
    try:
        re.compile(args.trigger_scheduled)
    except re.error as exc:
        ap.error(str(exc))
    data = report(args)
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print("source       start      model                    turns maxctxK meanctxK readM writeM outputK equivM ! session")
    for r in data["sessions"]:
        usage = f'{r["cache_read_tokens"]/1e6:6.2f} {r["cache_write_tokens"]/1e6:6.2f} {r["output_tokens"]/1e3:7.1f} {r["input_equivalent"]/1e6:6.2f}'
        print(f'{r["source"]:12} {r["start"]:10} {r["model"]:24} {r["turns"]:5} {r["max_context"]/1e3:7.1f} {r["mean_context"]/1e3:8.1f} {usage} {"!" if r["warning"] else " "} {r["session"]}')
    print(f'Totals ({data["total_sessions"]} sessions; all rows before --top):')
    print("  " + ", ".join(f"{k}={v:,.0f}" for k, v in data["totals"].items()))
    print("Claude input-equivalent share: " + ", ".join(f"{k} {v:.1%}" for k, v in data["trigger_shares"].items()))
    if data["t3_threads"]:
        print(f'\nT3 threads ({data["total_t3_threads"]}; context per turn only, sorted by turns x mean context):')
        print("start      model                    turns maxctxK meanctxK ! thread")
        for r in data["t3_threads"]:
            print(f'{r["start"]:10} {str(r["model"]):24} {r["turns"]:5} {r["max_context"]/1e3:7.1f} {r["mean_context"]/1e3:8.1f} {"!" if r["warning"] else " "} {r["session"]}')
    for note in data["notes"]:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
