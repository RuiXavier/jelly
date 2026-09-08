#!/usr/bin/env bash
# Run plain Jelly (points-to/call-graph only, no -v) over every module case
# in one SecBench.js vulnerability class, to check for scalability issues
# (hangs, crashes, OOM) independent of any downstream taint analysis.
#
# Usage: run_secbench_class.sh <secbench-class-dir> <jelly-repo-dir> <results-dir>
set -u

CLASS_DIR="$1"        # e.g. .../SecBench.js/command-injection
JELLY_DIR="$2"        # e.g. .../jelly (must already be built: lib/main.js exists)
RESULTS_DIR="$3"      # where to write logs + summary.csv

MAIN_JS="$JELLY_DIR/lib/main.js"
if [ ! -f "$MAIN_JS" ]; then
    echo "Jelly not built: $MAIN_JS not found (run npm install && npm run build in $JELLY_DIR)" >&2
    exit 1
fi

mkdir -p "$RESULTS_DIR/logs"
SUMMARY="$RESULTS_DIR/summary.csv"
echo "module,npm_install,jelly_exit,seconds,note" > "$SUMMARY"

# Safety net only (not a "failure" cutoff) so one hung case can't stall the
# whole batch indefinitely. Generous on purpose.
SAFETY_TIMEOUT=1800

count=0
for dir in "$CLASS_DIR"/*/; do
    [ -d "$dir" ] || continue
    module=$(basename "$dir")
    test_file=$(find "$dir" -maxdepth 1 -iname '*.test.js' | head -1)
    if [ -z "$test_file" ]; then
        echo "$module,skip,skip,0,no .test.js file found" >> "$SUMMARY"
        continue
    fi
    count=$((count+1))
    log="$RESULTS_DIR/logs/$module.log"
    echo "[$count] $module"

    npm_status="skipped(already-installed)"
    if [ ! -d "$dir/node_modules" ]; then
        if (cd "$dir" && npm install --no-audit --no-fund --silent) >> "$log" 2>&1; then
            npm_status="ok"
        else
            npm_status="failed"
            echo "$module,$npm_status,n/a,0,npm install failed" >> "$SUMMARY"
            continue
        fi
    fi

    start=$(date +%s.%N)
    timeout "$SAFETY_TIMEOUT" node "$MAIN_JS" "$test_file" --basedir "$dir" >> "$log" 2>&1
    exit_code=$?
    end=$(date +%s.%N)
    elapsed=$(awk "BEGIN {printf \"%.2f\", $end - $start}")

    note=""
    if [ "$exit_code" -eq 124 ]; then
        note="hit ${SAFETY_TIMEOUT}s safety cap (still running)"
    elif [ "$exit_code" -ne 0 ]; then
        note="non-zero exit (see log)"
    fi
    echo "$module,$npm_status,$exit_code,$elapsed,$note" >> "$SUMMARY"
done

echo ""
echo "Done: $count cases. Summary at $SUMMARY"
