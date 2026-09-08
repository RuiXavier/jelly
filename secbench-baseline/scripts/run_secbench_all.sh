#!/usr/bin/env bash
# Run plain Jelly (points-to/call-graph only, no -v/-taint) over every module
# case in all official SecBench.js vulnerability classes, to build a baseline
# of runtime/call-graph/memory statistics before layering taint analysis.
#
# Usage: run_secbench_all.sh <secbench-repo-dir> <jelly-repo-dir> <results-dir>
set -u

SB_DIR="$1"
JELLY_DIR="$2"
RESULTS_DIR="$3"

MAIN_JS="$JELLY_DIR/lib/main.js"
if [ ! -f "$MAIN_JS" ]; then
    echo "Jelly not built: $MAIN_JS not found (run npm install && npm run build in $JELLY_DIR)" >&2
    exit 1
fi

CLASSES=(prototype-pollution redos command-injection path-traversal code-injection)

mkdir -p "$RESULTS_DIR/logs"
SUMMARY="$RESULTS_DIR/summary.csv"
echo "class,module,npm_install,jelly_exit,seconds,note" > "$SUMMARY"

# Safety net only (not a "failure" cutoff) so one hung case can't stall the
# whole batch indefinitely. Generous on purpose.
SAFETY_TIMEOUT=1800
export NODE_OPTIONS="--max-old-space-size=8192"

count=0
for cls in "${CLASSES[@]}"; do
    class_dir="$SB_DIR/$cls"
    [ -d "$class_dir" ] || { echo "missing class dir: $class_dir" >&2; continue; }
    for dir in "$class_dir"/*/; do
        [ -d "$dir" ] || continue
        module=$(basename "$dir")
        test_file=$(find "$dir" -maxdepth 1 -iname '*.test.js' | head -1)
        if [ -z "$test_file" ]; then
            echo "$cls,$module,skip,skip,0,no .test.js file found (malformed case dir)" >> "$SUMMARY"
            continue
        fi
        count=$((count+1))
        log="$RESULTS_DIR/logs/${cls}__${module}.log"
        echo "[$count] $cls/$module"

        npm_status="n/a(no-package.json)"
        if [ -f "$dir/package.json" ]; then
            if [ -d "$dir/node_modules" ]; then
                npm_status="skipped(already-installed)"
            elif (cd "$dir" && npm install --no-audit --no-fund --silent) >> "$log" 2>&1; then
                npm_status="ok"
            else
                npm_status="failed"
                echo "$cls,$module,$npm_status,n/a,0,npm install failed" >> "$SUMMARY"
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
        echo "$cls,$module,$npm_status,$exit_code,$elapsed,$note" >> "$SUMMARY"
    done
done

echo ""
echo "Done: $count cases. Summary at $SUMMARY"
