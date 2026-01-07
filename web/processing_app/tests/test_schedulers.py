"""
Tests for processing_app schedulers.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, time as dt_time
from processing_app.models import ContentProcessingJob, ProcessingSchedule
from processing_app.schedulers import DailyScheduler
from twitter.models import TwitterProfile


@pytest.mark.django_db
class TestDailyScheduler:
    """Tests for DailyScheduler."""
    
    def test_should_schedule_job_valid(self, user, twitter_profile):
        """Test should_schedule_job returns True for valid case."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
        )
        
        scheduler = DailyScheduler()
        assert scheduler.should_schedule_job(user, 'bookmarks', date.today()) is True
    
    def test_should_schedule_job_disabled_schedule(self, user, twitter_profile):
        """Test should_schedule_job returns False when schedule is disabled."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=False,
            process_bookmarks=True,
        )
        
        scheduler = DailyScheduler()
        assert scheduler.should_schedule_job(user, 'bookmarks', date.today()) is False
    
    def test_should_schedule_job_content_type_disabled(self, user, twitter_profile):
        """Test should_schedule_job returns False when content type is disabled."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=False,  # Disabled
        )
        
        scheduler = DailyScheduler()
        assert scheduler.should_schedule_job(user, 'bookmarks', date.today()) is False
    
    def test_should_schedule_job_already_exists(self, user, twitter_profile):
        """Test should_schedule_job returns False when job already exists."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
        )
        
        # Create existing job
        ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        scheduler = DailyScheduler()
        assert scheduler.should_schedule_job(user, 'bookmarks', date.today()) is False
    
    @patch('processing_app.schedulers.async_task')
    def test_schedule_user_jobs_immediate(self, mock_async_task, user, twitter_profile):
        """Test scheduling user jobs with immediate flag."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
        )
        
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=True)
        
        assert len(jobs) == 1
        assert jobs[0].content_type == 'bookmarks'
        assert jobs[0].status == 'pending'
        # Should queue immediately
        mock_async_task.assert_called_once()
    
    @patch('processing_app.schedulers.schedule')
    def test_schedule_user_jobs_scheduled(self, mock_schedule, user, twitter_profile):
        """Test scheduling user jobs without immediate flag."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
        )
        
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=False)
        
        assert len(jobs) == 1
        # Should schedule for later
        mock_schedule.assert_called_once()
    
    def test_schedule_user_jobs_creates_default_schedule(self, user, twitter_profile):
        """Test schedule_user_jobs creates default schedule if missing."""
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=True)
        
        # Should create default schedule
        schedule = ProcessingSchedule.objects.get(user=user)
        assert schedule.enabled is True
        assert schedule.processing_time == dt_time(2, 0)
        assert len(jobs) > 0

