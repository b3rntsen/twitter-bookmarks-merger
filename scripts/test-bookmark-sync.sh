#!/bin/bash
# Post-deployment E2E test for bookmark sync system
# Verifies that scheduling system is working correctly

set -e

SSH_KEY="${SSH_KEY:-$HOME/.ssh/twitter-bookmarks-key.pem}"
SERVER_USER="${SERVER_USER:-ec2-user}"
SERVER_HOST="${SERVER_HOST:-13.62.72.70}"

echo "🧪 Testing bookmark sync system..."
echo ""

ssh -i "$SSH_KEY" "${SERVER_USER}@${SERVER_HOST}" << 'ENDSSH'
set -e
cd twitter-bookmarks

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 1: Cleaning old schedules"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

docker compose -f docker-compose.prod.yml exec -T web python manage.py shell << 'EOF'
from django_q.models import Schedule
from django.utils import timezone

deleted = Schedule.objects.filter(next_run__lt=timezone.now()).delete()
print(f"✓ Deleted {deleted[0]} old schedule(s)")
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 2: Scheduling next sync"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

docker compose -f docker-compose.prod.yml exec -T web python manage.py shell << 'EOF'
from twitter.tasks import schedule_next_bookmark_sync
from twitter.models import TwitterProfile

# Get first enabled profile
profile = TwitterProfile.objects.filter(sync_schedule__enabled=True).first()
if not profile:
    print("❌ No enabled profiles found")
    exit(1)

print(f"Testing with profile: {profile.twitter_username} (ID: {profile.id})")
schedule_next_bookmark_sync(profile.id)
print("✓ schedule_next_bookmark_sync() completed without error")
EOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 3: Verifying schedule created"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

docker compose -f docker-compose.prod.yml exec -T web python manage.py shell << 'EOF'
from django_q.models import Schedule
from django.utils import timezone

future = Schedule.objects.filter(next_run__gt=timezone.now()).order_by('next_run')
count = future.count()

if count > 0:
    print(f"✅ SUCCESS: {count} future schedule(s) created")
    print("")
    for s in future:
        time_until = (s.next_run - timezone.now()).total_seconds() / 60
        print(f"  - {s.name}")
        print(f"    Next run: {s.next_run}")
        print(f"    In {time_until:.1f} minutes")
        print("")
else:
    print("❌ FAILURE: No future schedules created")
    print("")
    print("This means schedule_next_bookmark_sync() didn't create Django-Q Schedule entries")
    print("Check:")
    print("  1. Is schedule() function being called correctly?")
    print("  2. Are there errors in qcluster logs?")
    print("  3. Is Django-Q cluster running?")
    exit(1)
EOF

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Bookmark sync system test PASSED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ENDSSH

echo ""
echo "Next: Monitor Django-Q logs to verify scheduled execution:"
echo "  ssh -i $SSH_KEY ${SERVER_USER}@${SERVER_HOST} 'cd twitter-bookmarks && docker compose -f docker-compose.prod.yml logs -f qcluster'"
