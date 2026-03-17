#!/bin/bash
# Pre-deployment dependency tracing - fails if dependencies not identified
# Usage: ./scripts/verify-deployment.sh <file1.py> <file2.py> ...

echo "🔍 Dependency Tracing..."
echo ""

if [ $# -eq 0 ]; then
    echo "❌ Error: No files specified"
    echo "Usage: $0 <file1.py> <file2.py> ..."
    exit 1
fi

FOUND_DEPS=0
DEPLOYMENT_LIST=""

for file in "$@"; do
    if [ ! -f "$file" ]; then
        echo "⚠️  Warning: File not found: $file"
        continue
    fi

    echo "Analyzing $file..."

    # Check subprocess calls
    if grep -q "subprocess\|os\.system" "$file"; then
        echo "  ⚠️  SUBPROCESS CALLS FOUND:"
        grep -n "subprocess\|os\.system" "$file" | head -5
        echo "  → Verify all binaries/scripts exist in containers"
        FOUND_DEPS=1
        DEPLOYMENT_LIST="$DEPLOYMENT_LIST\n  - External scripts/binaries from $file"
    fi

    # Check imports
    if grep -q "^import \|^from " "$file"; then
        echo "  ⚠️  IMPORTS FOUND:"
        grep -n "^import \|^from " "$file" | head -10
        echo "  → Verify all modules deployed to containers"
        FOUND_DEPS=1
        DEPLOYMENT_LIST="$DEPLOYMENT_LIST\n  - Python modules imported by $file"
    fi

    # Check file operations
    if grep -q "open(\|Path(\|\.read_text\|\.read_bytes" "$file"; then
        echo "  ⚠️  FILE OPERATIONS FOUND:"
        grep -n "open(\|Path(\|\.read_text\|\.read_bytes" "$file" | head -5
        echo "  → Verify all files/directories exist in containers"
        FOUND_DEPS=1
        DEPLOYMENT_LIST="$DEPLOYMENT_LIST\n  - Files/directories accessed by $file"
    fi

    echo ""
done

if [ $FOUND_DEPS -eq 1 ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  DEPENDENCIES DETECTED - CREATE DEPLOYMENT CHECKLIST"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Files to deploy:$DEPLOYMENT_LIST"
    echo ""
    echo "Next steps:"
    echo "  1. List ALL files needed (code + dependencies)"
    echo "  2. Verify files exist in containers (web + qcluster):"
    echo "     docker exec twitter-bookmarks-web-1 ls -la /app/path/to/file"
    echo "     docker exec twitter-bookmarks-qcluster-1 ls -la /app/path/to/file"
    echo "  3. Deploy missing files to ALL containers"
    echo "  4. Run E2E test to verify functionality"
    echo ""
    exit 1
else
    echo "✅ No external dependencies detected"
    echo ""
    echo "Reminder: Still verify the changed files are deployed to all containers!"
fi
