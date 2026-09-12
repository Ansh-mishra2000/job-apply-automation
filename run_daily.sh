#!/usr/bin/env bash
# ==============================================================================
# Job Application Automation Daily Runner
# Usage:
#   ./run_daily.sh                  # Runs with interactive prompt or config default
#   ./run_daily.sh --headless       # Runs silently in background (ideal for cron)
#   ./run_daily.sh --visible        # Runs with visible browser
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

mkdir -p "$SCRIPT_DIR/data/logs"

# Check if running in a non-interactive environment (e.g. cron)
if [ ! -t 0 ] && [ $# -eq 0 ]; then
    RUN_ARGS="--headless"
else
    RUN_ARGS="$@"
fi

# Activate virtual environment
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "[Error] Virtual environment .venv not found. Please run: python3 -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# Execute main job apply process
python3 "$SCRIPT_DIR/main.py" run $RUN_ARGS >> "$SCRIPT_DIR/data/logs/cron.log" 2>&1
