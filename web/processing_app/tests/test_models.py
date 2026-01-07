"""
Tests for processing_app models.
"""
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, time as dt_time
from processing_app.models import ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot
from twitter.models import TwitterProfile


@pytest.mark.django_db
class TestContentProcessingJob:
    """Tests for ContentProcessingJob model."""
    
    def test_job_creation(self, user, twitter_profile):
        """Test creating a ContentProcessingJob."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        assert job.user == user
        assert job.twitter_profile == twitter_profile
        assert job.content_type == 'bookmarks'
        assert job.status == 'pending'
        assert job.retry_count == 0
        assert job.max_retries == 5
    
    def test_job_status_transitions(self, user, twitter_profile):
        """Test job status transitions."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        # Transition to running
        job.status = 'running'
        job.started_at = timezone.now()
        job.save()
        assert job.status == 'running'
        
        # Transition to completed
        job.status = 'completed'
        job.completed_at = timezone.now()
        job.items_processed = 10
        job.save()
        assert job.status == 'completed'
        assert job.items_processed == 10
    
    def test_job_retry_count(self, user, twitter_profile):
        """Test retry count increments."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='failed',
            scheduled_at=timezone.now(),
            retry_count=0,
        )
        
        job.retry_count += 1
        job.status = 'retrying'
        job.save()
        
        assert job.retry_count == 1
        assert job.status == 'retrying'
    
    def test_job_unique_constraint(self, user, twitter_profile):
        """Test unique constraint on user/twitter_profile/content_type/processing_date."""
        job1 = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        # Try to create duplicate
        with pytest.raises(Exception):  # Should raise IntegrityError
            ContentProcessingJob.objects.create(
                user=user,
                twitter_profile=twitter_profile,
                content_type='bookmarks',
                processing_date=date.today(),
                status='pending',
                scheduled_at=timezone.now(),
            )


@pytest.mark.django_db
class TestProcessingSchedule:
    """Tests for ProcessingSchedule model."""
    
    def test_schedule_creation(self, user):
        """Test creating a ProcessingSchedule."""
        schedule = ProcessingSchedule.objects.create(
            user=user,
            processing_time=dt_time(2, 0),
            timezone='UTC',
            enabled=True,
        )
        
        assert schedule.user == user
        assert schedule.processing_time == dt_time(2, 0)
        assert schedule.timezone == 'UTC'
        assert schedule.enabled is True
        assert schedule.process_bookmarks is True
        assert schedule.process_curated_feed is True
        assert schedule.process_lists is True
    
    def test_schedule_defaults(self, user):
        """Test ProcessingSchedule default values."""
        schedule = ProcessingSchedule.objects.create(user=user)
        
        assert schedule.processing_time == dt_time(2, 0)
        assert schedule.timezone == 'UTC'
        assert schedule.enabled is True
        assert schedule.process_bookmarks is True
        assert schedule.process_curated_feed is True
        assert schedule.process_lists is True
    
    def test_schedule_one_to_one_user(self, user):
        """Test one-to-one relationship with User."""
        schedule1 = ProcessingSchedule.objects.create(user=user)
        
        # Should not be able to create another schedule for same user
        with pytest.raises(Exception):  # Should raise IntegrityError
            ProcessingSchedule.objects.create(user=user)


@pytest.mark.django_db
class TestDailyContentSnapshot:
    """Tests for DailyContentSnapshot model."""
    
    def test_snapshot_creation(self, user, twitter_profile):
        """Test creating a DailyContentSnapshot."""
        snapshot = DailyContentSnapshot.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today(),
            bookmark_count=10,
            curated_feed_count=5,
            list_count=3,
            total_tweet_count=18,
        )
        
        assert snapshot.user == user
        assert snapshot.twitter_profile == twitter_profile
        assert snapshot.processing_date == date.today()
        assert snapshot.bookmark_count == 10
        assert snapshot.total_tweet_count == 18
    
    def test_snapshot_content_counts(self, user, twitter_profile):
        """Test content count calculations."""
        snapshot = DailyContentSnapshot.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today(),
            bookmark_count=10,
            curated_feed_count=5,
            list_count=3,
        )
        
        # Total should be sum of all counts
        assert snapshot.total_tweet_count == 0  # Initially 0, should be updated
        snapshot.total_tweet_count = snapshot.bookmark_count + snapshot.curated_feed_count + snapshot.list_count
        snapshot.save()
        assert snapshot.total_tweet_count == 18
    
    def test_snapshot_all_jobs_completed(self, user, twitter_profile):
        """Test all_jobs_completed flag."""
        snapshot = DailyContentSnapshot.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today(),
            all_jobs_completed=False,
        )
        
        assert snapshot.all_jobs_completed is False
        
        snapshot.all_jobs_completed = True
        snapshot.last_processed_at = timezone.now()
        snapshot.save()
        
        assert snapshot.all_jobs_completed is True
        assert snapshot.last_processed_at is not None
    
    def test_snapshot_unique_constraint(self, user, twitter_profile):
        """Test unique constraint on user/twitter_profile/processing_date."""
        snapshot1 = DailyContentSnapshot.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today(),
        )
        
        # Try to create duplicate
        with pytest.raises(Exception):  # Should raise IntegrityError
            DailyContentSnapshot.objects.create(
                user=user,
                twitter_profile=twitter_profile,
                processing_date=date.today(),
            )

