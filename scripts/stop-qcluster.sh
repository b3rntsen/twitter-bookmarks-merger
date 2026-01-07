#!/bin/bash
# Stop Django-Q cluster

cd "$(dirname "$0")/.."

echo "Stopping Django-Q cluster..."

# Find all qcluster processes (parent and children)
PIDS=$(pgrep -f "python.*manage.py qcluster" 2>/dev/null)

if [ -z "$PIDS" ]; then
    echo "⚠️  No running cluster found"
    exit 0
fi

# Kill all processes (including child processes)
for PID in $PIDS; do
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping process $PID..."
        # First try graceful termination
        kill $PID 2>/dev/null
    fi
done

# Wait a moment for graceful shutdown
sleep 2

# Force kill any remaining processes
REMAINING=$(pgrep -f "python.*manage.py qcluster" 2>/dev/null)
if [ -n "$REMAINING" ]; then
    echo "Force killing remaining processes..."
    for PID in $REMAINING; do
        if ps -p $PID > /dev/null 2>&1; then
            kill -9 $PID 2>/dev/null
        fi
    done
    sleep 1
fi

# Verify all processes are stopped
FINAL_CHECK=$(pgrep -f "python.*manage.py qcluster" 2>/dev/null)
if [ -z "$FINAL_CHECK" ]; then
    echo "✅ Django-Q cluster stopped"
else
    echo "⚠️  Some processes may still be running: $FINAL_CHECK"
    echo "   You may need to manually kill them: kill -9 $FINAL_CHECK"
fi

