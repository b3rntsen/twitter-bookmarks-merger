"""Django-Q tasks for bookmark synchronization."""
import subprocess
import sys
import re
import logging
from pathlib import Path
from datetime import timedelta
from django.utils import timezone
from django_q.tasks import schedule as q_schedule
from django_q.models import Schedule as DjangoQSchedule
from .models import TwitterProfile, BookmarkSyncJob, BookmarkSyncSchedule

logger = logging.getLogger(__name__)


def execute_bookmark_sync(sync_job_id: int):
    """
    Execute bookmark sync via birdmarks_bridge.py.
    Called by Django-Q worker.
    """
    try:
        job = BookmarkSyncJob.objects.select_related('twitter_profile', 'twitter_profile__sync_schedule').get(id=sync_job_id)
        profile = job.twitter_profile
        schedule = profile.sync_schedule

        # Build command to run birdmarks_bridge.py
        bridge_script = Path(__file__).parent.parent.parent / "tools" / "birdmarks_bridge.py"

        cmd = [
            sys.executable,
            str(bridge_script),
            "--max-pages", str(schedule.max_pages)
        ]

        if schedule.use_until_synced:
            cmd.append("--until-synced")

        # Mark as running just before execution (fix race condition)
        job.status = 'running'
        job.started_at = timezone.now()
        job.save()

        logger.info(f"Starting bookmark sync for {profile.twitter_username} (job #{job.id})")

        # Execute with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10-minute timeout
        )

        # Parse output for success indicators
        stdout = result.stdout
        stderr = result.stderr

        # Extract bookmarks count from output
        # Look for patterns like "Exported: 42 bookmarks" or "✅ Converted 42 NEW bookmarks"
        match = re.search(r'(?:Exported:|Converted)\s+(\d+)', stdout)
        bookmarks_count = int(match.group(1)) if match else 0

        # Check for success
        if result.returncode == 0:
            job.status = 'success'
            job.bookmarks_fetched = bookmarks_count
            job.completed_at = timezone.now()

            # Reset consecutive failures
            schedule.consecutive_failures = 0

            # Update TwitterProfile
            profile.last_sync_at = timezone.now()
            profile.sync_status = 'success'
            profile.sync_error_message = ''

            logger.info(f"Bookmark sync successful for {profile.twitter_username}: {bookmarks_count} bookmarks")
        else:
            # Parse error type
            error_type = 'unknown'
            error_text = stderr + stdout  # Check both streams

            if 'auth_token' in error_text or 'ct0' in error_text or 'Cookies file not found' in error_text:
                error_type = 'cookie_expired'
            elif 'timeout' in error_text.lower():
                error_type = 'timeout'
            elif 'rate limit' in error_text.lower():
                error_type = 'rate_limit'
            else:
                error_type = 'fetch_error'

            job.status = 'failed'
            job.error_message = stderr[:1000] if stderr else stdout[:1000]  # Truncate
            job.error_type = error_type
            job.completed_at = timezone.now()

            # Increment consecutive failures
            schedule.consecutive_failures += 1

            logger.error(f"Bookmark sync failed for {profile.twitter_username}: {error_type}")

            # Update TwitterProfile
            profile.sync_status = 'error'
            profile.sync_error_message = f"{error_type}: {(stderr or stdout)[:200]}"

        profile.save()
        schedule.save()
        job.save()

        # Check if we should disable due to excessive failures
        if schedule.should_disable_due_to_failures():
            schedule.disable_due_to_failures()
            profile.sync_status = 'error'
            profile.sync_error_message = f'Sync disabled after {schedule.consecutive_failures} consecutive failures'
            profile.save()
        elif schedule.enabled:
            # Schedule next sync
            schedule_next_bookmark_sync(profile.id)

    except subprocess.TimeoutExpired:
        # Timeout error
        job.status = 'failed'
        job.error_message = 'Sync timed out after 10 minutes'
        job.error_type = 'timeout'
        job.completed_at = timezone.now()
        job.save()

        logger.error(f"Bookmark sync timeout for job #{job.id}")

        # Refetch profile to avoid stale data
        try:
            profile_refresh = TwitterProfile.objects.select_related('sync_schedule').get(id=job.twitter_profile_id)
            schedule = profile_refresh.sync_schedule
            schedule.consecutive_failures += 1
            schedule.save()

            # Check if we should disable
            if schedule.should_disable_due_to_failures():
                schedule.disable_due_to_failures()
                profile_refresh.sync_status = 'error'
                profile_refresh.sync_error_message = f'Sync disabled after {schedule.consecutive_failures} consecutive failures'
                profile_refresh.save()
            elif schedule.enabled:
                schedule_next_bookmark_sync(profile_refresh.id)
        except Exception as schedule_error:
            logger.error(f"Failed to schedule next sync after timeout for profile {job.twitter_profile_id}: {schedule_error}")

    except Exception as e:
        # Unexpected error - log full traceback
        logger.exception(f"Unexpected error in bookmark sync job {sync_job_id}: {e}")

        job.status = 'failed'
        job.error_message = str(e)[:1000]
        job.error_type = 'system_error'
        job.completed_at = timezone.now()
        job.save()

        # Refetch profile to avoid stale data
        try:
            profile_refresh = TwitterProfile.objects.select_related('sync_schedule').get(id=job.twitter_profile_id)
            schedule = profile_refresh.sync_schedule
            schedule.consecutive_failures += 1
            schedule.save()

            # Check if we should disable
            if schedule.should_disable_due_to_failures():
                schedule.disable_due_to_failures()
                profile_refresh.sync_status = 'error'
                profile_refresh.sync_error_message = f'Sync disabled after {schedule.consecutive_failures} consecutive failures'
                profile_refresh.save()
            elif schedule.enabled:
                schedule_next_bookmark_sync(profile_refresh.id)
        except Exception as schedule_error:
            logger.error(f"Failed to schedule next sync after error for profile {job.twitter_profile_id}: {schedule_error}")


def schedule_next_bookmark_sync(twitter_profile_id: int):
    """
    Schedule the next bookmark sync for a profile.
    """
    try:
        profile = TwitterProfile.objects.select_related('sync_schedule').get(id=twitter_profile_id)
        schedule = profile.sync_schedule

        if not schedule.enabled:
            logger.info(f"Skipping schedule for {profile.twitter_username} - schedule disabled")
            return

        # Calculate next sync time
        next_sync = schedule.calculate_next_sync()

        # Validate next_sync is in the future
        now = timezone.now()
        if next_sync <= now:
            logger.warning(f"Calculated next_sync {next_sync} is not in future for {profile.twitter_username}, adjusting")
            next_sync = now + timedelta(minutes=schedule.interval_minutes)

        # Create pending job
        job = BookmarkSyncJob.objects.create(
            twitter_profile=profile,
            scheduled_at=next_sync,
            status='pending'
        )

        # Update schedule
        schedule.next_sync_at = next_sync
        schedule.last_scheduled_at = timezone.now()
        schedule.save()

        # Delete any existing Django-Q schedules for this profile to avoid duplicates
        existing = DjangoQSchedule.objects.filter(
            func='twitter.tasks.execute_bookmark_sync',
            args=str([job.id])
        ).first()
        if existing:
            logger.warning(f"Deleting existing Django-Q schedule {existing.id} for {profile.twitter_username}")
            existing.delete()

        # Create new schedule with unique name
        schedule_name = f"bookmark_sync_{profile.id}_{int(next_sync.timestamp())}"

        # Queue task with Django-Q
        q_schedule(
            'twitter.tasks.execute_bookmark_sync',
            job.id,
            name=schedule_name,
            schedule_type='O',  # 'O' = Once
            next_run=next_sync,
            repeats=1
        )

        logger.info(f"Scheduled bookmark sync for {profile.twitter_username} at {next_sync} (job #{job.id})")

    except BookmarkSyncSchedule.DoesNotExist:
        # No schedule configured, skip
        logger.warning(f"No sync schedule found for profile {twitter_profile_id}")
    except Exception as e:
        # Log error but don't raise
        logger.exception(f"Error scheduling next sync for profile {twitter_profile_id}: {e}")
