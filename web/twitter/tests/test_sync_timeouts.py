"""
Timeout budget for bookmark syncs: the full rebuild gets its own, longer fetch
timeout, and the stuck-job reaper must not kill a full rebuild that is still
within it.
"""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from twitter.models import BookmarkSyncJob
from twitter.tasks import (
    BOUNDED_FETCH_TIMEOUT,
    FULL_REBUILD_TIMEOUT,
    STALE_RUNNING_MINUTES,
    fetch_timeout,
    recover_stuck_bookmark_syncs,
)

# Post-fetch pipeline (import, media, export, categorise, generate, publish).
# Observed at 1-2 minutes; allow generous headroom.
PIPELINE_ALLOWANCE = 10 * 60


def test_full_rebuild_gets_the_longer_timeout():
    assert fetch_timeout({'full_rebuild': True}) == FULL_REBUILD_TIMEOUT
    assert fetch_timeout({'full_rebuild': False}) == BOUNDED_FETCH_TIMEOUT
    assert FULL_REBUILD_TIMEOUT > BOUNDED_FETCH_TIMEOUT


def test_reaper_outlasts_a_full_rebuild():
    assert STALE_RUNNING_MINUTES * 60 >= FULL_REBUILD_TIMEOUT + PIPELINE_ALLOWANCE


def test_django_q_task_timeout_outlasts_a_full_rebuild():
    assert settings.Q_CLUSTER['timeout'] >= FULL_REBUILD_TIMEOUT + PIPELINE_ALLOWANCE


def _running_job(profile, minutes_ago):
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return BookmarkSyncJob.objects.create(
        twitter_profile=profile,
        scheduled_at=started,
        started_at=started,
        status='running',
    )


@pytest.mark.django_db
def test_watchdog_leaves_a_long_full_rebuild_running(twitter_profile):
    # 35 minutes in: past the old 30-minute cutoff, inside the full-rebuild budget.
    job = _running_job(twitter_profile, minutes_ago=35)
    recover_stuck_bookmark_syncs()
    job.refresh_from_db()
    assert job.status == 'running'


@pytest.mark.django_db
def test_watchdog_reaps_a_job_past_the_cutoff(twitter_profile):
    job = _running_job(twitter_profile, minutes_ago=STALE_RUNNING_MINUTES + 5)
    recover_stuck_bookmark_syncs()
    job.refresh_from_db()
    assert job.status == 'failed'
    assert job.error_type == 'stale_job'
