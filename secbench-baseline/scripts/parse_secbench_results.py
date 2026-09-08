#!/usr/bin/env python3
"""Parse Jelly's stdout logs from a SecBench.js baseline run into one CSV
with per-case metrics, plus an aggregate JSON summary (overall + per class).
"""
import csv
import json
import re
import statistics
import sys
from pathlib import Path

RE_ANALYZED = re.compile(
    r"Analyzed packages: (\d+), modules: (\d+), functions: (\d+), "
    r"code size main: (\d+)KB, dependencies: (\d+)KB"
)
RE_EDGES = re.compile(r"Call edges function->function: (\d+), call->function: (\d+)")
RE_CALLS = re.compile(
    r"Calls with zero or one callee: (\d+)/(\d+) \(([\d.]+)%\), "
    r"multiple: (\d+)/(\d+) \(([\d.]+)%\), "
    r"native or external: (\d+)/(\d+) \(([\d.]+)%\)"
)
RE_FUNCS = re.compile(
    r"Functions with zero callers: (\d+)/(\d+) \(([\d.]+)%\), "
    r"reachable functions: (\d+)/(\d+) \(([\d.]+)%\)"
)
RE_TIME = re.compile(r"Analysis time: (\d+)ms, memory usage: (\d+)MB")
RE_ERRWARN = re.compile(r"Analysis errors: (\d+), warnings: (\d+)")
RE_OOM = re.compile(r"JavaScript heap out of memory|FATAL ERROR")
RE_UNRESOLVED = re.compile(r"Unable to resolve")


def parse_log(path: Path) -> dict:
    text = path.read_text(errors="replace")
    row = {}
    if m := RE_ANALYZED.search(text):
        row.update(
            packages=int(m[1]), modules=int(m[2]), functions=int(m[3]),
            code_size_main_kb=int(m[4]), dependencies_kb=int(m[5]),
        )
    if m := RE_EDGES.search(text):
        row.update(edges_fun2fun=int(m[1]), edges_call2fun=int(m[2]))
    if m := RE_CALLS.search(text):
        row.update(
            calls_zero_or_one_pct=float(m[3]),
            calls_multiple_pct=float(m[6]),
            calls_native_external_pct=float(m[9]),
            calls_total=int(m[2]),
        )
    if m := RE_FUNCS.search(text):
        row.update(
            funcs_zero_callers_pct=float(m[3]),
            funcs_reachable_pct=float(m[6]),
        )
    if m := RE_TIME.search(text):
        row.update(jelly_time_ms=int(m[1]), jelly_memory_mb=int(m[2]))
    if m := RE_ERRWARN.search(text):
        row.update(errors=int(m[1]), warnings=int(m[2]))
    row["oom"] = bool(RE_OOM.search(text))
    row["unresolved_module_warnings"] = len(RE_UNRESOLVED.findall(text))
    return row


def main():
    results_dir = Path(sys.argv[1])
    summary_csv = results_dir / "summary.csv"
    logs_dir = results_dir / "logs"
    out_csv = results_dir / "parsed.csv"
    out_json = results_dir / "aggregate.json"

    fieldnames = [
        "class", "module", "npm_install", "jelly_exit", "seconds", "note",
        "packages", "modules", "functions", "code_size_main_kb", "dependencies_kb",
        "edges_fun2fun", "edges_call2fun",
        "calls_zero_or_one_pct", "calls_multiple_pct", "calls_native_external_pct", "calls_total",
        "funcs_zero_callers_pct", "funcs_reachable_pct",
        "jelly_time_ms", "jelly_memory_mb", "errors", "warnings",
        "oom", "unresolved_module_warnings",
    ]

    rows = []
    with summary_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            row = dict(r)
            log_path = logs_dir / f"{r['class']}__{r['module']}.log"
            if log_path.exists():
                row.update(parse_log(log_path))
            rows.append(row)

    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)

    def bucket(rows):
        total = len(rows)
        npm_failed = [r for r in rows if r.get("npm_install") == "failed"]
        skipped = [r for r in rows if r.get("npm_install") == "skip" or r.get("jelly_exit") == "skip"]
        analyzed = [r for r in rows if r not in npm_failed and r not in skipped]
        oom = [r for r in analyzed if r.get("oom")]
        clean_success = [r for r in analyzed if r.get("jelly_exit") == "0" and not r.get("oom")]
        other_fail = [r for r in analyzed if r.get("jelly_exit") not in ("0",) and not r.get("oom")]

        def stats_for(key, source):
            vals = [float(r[key]) for r in source if r.get(key) not in (None, "")]
            if not vals:
                return None
            vals.sort()
            return {
                "n": len(vals),
                "min": vals[0],
                "max": vals[-1],
                "mean": round(statistics.mean(vals), 2),
                "median": round(statistics.median(vals), 2),
                "p90": round(vals[int(len(vals) * 0.9) - 1], 2) if len(vals) >= 10 else None,
            }

        return {
            "total_cases": total,
            "npm_install_failed": len(npm_failed),
            "skipped_malformed": len(skipped),
            "analyzed": len(analyzed),
            "clean_success": len(clean_success),
            "oom_or_crash": len(oom),
            "other_nonzero_exit": len(other_fail),
            "wall_seconds": stats_for("seconds", clean_success),
            "jelly_reported_time_ms": stats_for("jelly_time_ms", clean_success),
            "jelly_reported_memory_mb": stats_for("jelly_memory_mb", clean_success),
            "modules": stats_for("modules", clean_success),
            "functions": stats_for("functions", clean_success),
            "packages": stats_for("packages", clean_success),
            "edges_call2fun": stats_for("edges_call2fun", clean_success),
            "funcs_reachable_pct": stats_for("funcs_reachable_pct", clean_success),
            "warnings": stats_for("warnings", clean_success),
            "errors": stats_for("errors", clean_success),
            "oom_cases": [f"{r['class']}/{r['module']}" for r in oom],
            "npm_failed_cases": [f"{r['class']}/{r['module']}" for r in npm_failed],
            "other_fail_cases": [f"{r['class']}/{r['module']} (exit={r.get('jelly_exit')})" for r in other_fail],
            "top10_slowest": sorted(
                [{"case": f"{r['class']}/{r['module']}", "seconds": float(r["seconds"])} for r in clean_success],
                key=lambda x: -x["seconds"],
            )[:10],
            "top10_largest_callgraph": sorted(
                [{"case": f"{r['class']}/{r['module']}", "modules": int(r["modules"]), "functions": int(r["functions"])}
                 for r in clean_success if r.get("modules")],
                key=lambda x: -x["modules"],
            )[:10],
        }

    classes = sorted(set(r["class"] for r in rows))
    aggregate = {
        "overall": bucket(rows),
        "by_class": {cls: bucket([r for r in rows if r["class"] == cls]) for cls in classes},
    }

    out_json.write_text(json.dumps(aggregate, indent=2))
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_json}")
    print(json.dumps(aggregate["overall"], indent=2))


if __name__ == "__main__":
    main()
