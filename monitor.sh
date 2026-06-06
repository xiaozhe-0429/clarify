#!/bin/bash
TASKS_DIR="$HOME/agent-shared/tasks"
LOG_FILE="/tmp/clarify-monitor.log"
LOCK_FILE="/tmp/clarify-monitor.lock"

if [ -f "$LOCK_FILE" ]; then
    lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$lock_age" -lt 300 ]; then
        exit 0
    fi
fi
touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

check_tasks() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M')
    local report="## [Hermes] Clarify v1 进度报告 | $ts"
    local m1_done=true

    # Map task prefix → label, with fallback filenames
    get_status() {
        local prefix=$1 label=$2
        local file
        file=$(ls $TASKS_DIR/${prefix}-clarify.md 2>/dev/null)
        [ -z "$file" ] && file=$(ls $TASKS_DIR/${prefix}.md 2>/dev/null)
        if [ -n "$file" ]; then
            grep '^status:' "$file" | head -1 | sed 's/^status:[[:space:]]*//'
        else
            echo "NOT_FOUND"
        fi
    }

    local s
    s=$(get_status "T-20260605-clarify-m1-1" "M1-1")
    report+=" M1-1:$s"
    [ "$s" != "done" ] && m1_done=false

    s=$(get_status "T-20260605-clarify-m1-2" "M1-2")
    report+=" M1-2:$s"
    [ "$s" != "done" ] && m1_done=false

    s=$(get_status "T-20260605-clarify-m1-3" "M1-3")
    report+=" M1-3:$s"
    [ "$s" != "done" ] && m1_done=false

    s=$(get_status "T-20260605-2255-m2-1" "M2-1")
    report+=" M2-1:$s"

    if $m1_done; then
        report+=" | M1 完成，可联调"
    fi

    echo "$report" >> "$LOG_FILE"
    echo "$report"
}

check_tasks
while true; do
    sleep 600
    check_tasks
done
