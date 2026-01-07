#!/bin/bash
# Start Django-Q cluster in the background
# This script ensures the virtual environment is activated

cd "$(dirname "$0")/.."

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found. Please create one first."
    exit 1
fi

# Check if cluster is already running (verify process is actually alive)
EXISTING_PIDS=$(pgrep -f "python.*manage.py qcluster" 2>/dev/null)
if [ -n "$EXISTING_PIDS" ]; then
    # Verify at least one process is actually running
    ALIVE_PIDS=""
    for PID in $EXISTING_PIDS; do
        if ps -p $PID > /dev/null 2>&1; then
            ALIVE_PIDS="$ALIVE_PIDS $PID"
        fi
    done
    
    if [ -n "$ALIVE_PIDS" ]; then
        echo "⚠️  Django-Q cluster is already running (PIDs: $ALIVE_PIDS)"
        echo "   To stop it, run: ./scripts/stop-qcluster.sh"
        exit 0
    else
        # Clean up stale PIDs
        echo "🧹 Cleaning up stale process references..."
    fi
fi

# Start Django-Q cluster in background
echo "Starting Django-Q cluster in background..."
# Use -u flag for unbuffered output so logs appear immediately
nohup python -u manage.py qcluster > qcluster.log 2>&1 &
CLUSTER_PID=$!

# Wait a moment to check if it started successfully
sleep 2

if ps -p $CLUSTER_PID > /dev/null; then
    echo "✅ Django-Q cluster started successfully (PID: $CLUSTER_PID)"
    echo "📋 Logs: tail -f qcluster.log"
    echo "🛑 Stop: ./scripts/stop-qcluster.sh"
else
    echo "❌ Failed to start Django-Q cluster. Check qcluster.log for errors."
    exit 1
fi

