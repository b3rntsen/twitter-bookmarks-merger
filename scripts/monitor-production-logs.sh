#!/bin/bash
# Monitor production logs for web and qcluster services
# Usage: ./scripts/monitor-production-logs.sh [filter]

set -e

SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"
PROJECT_DIR_REMOTE="/home/${SERVER_USER}/twitter-bookmarks"

FILTER="${1:-}"

if [ -n "$FILTER" ]; then
    # Monitor with filter
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
        "cd ${PROJECT_DIR_REMOTE} && docker compose -f docker-compose.prod.yml logs -f --timestamps web qcluster | grep -E '${FILTER}'"
else
    # Monitor all logs
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_HOST}" \
        "cd ${PROJECT_DIR_REMOTE} && docker compose -f docker-compose.prod.yml logs -f --timestamps web qcluster"
fi

