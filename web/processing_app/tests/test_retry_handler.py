"""
Tests for retry handler.
"""
import pytest
from django.utils import timezone
from datetime import timedelta
from processing_app.models import ContentProcessingJob
from processing_app.retry_handler import RetryHandler


@pytest.mark.django_db
class TestRetryHandler:
    """Tests for RetryHandler."""
    
    def test_get_retry_delay(self):
        """Test retry delay calculation."""
        assert RetryHandler.get_retry_delay(0) == 300  # 5 minutes
        assert RetryHandler.get_retry_delay(1) == 900  # 15 minutes
        assert RetryHandler.get_retry_delay(2) == 1800  # 30 minutes
        assert RetryHandler.get_retry_delay(3) == 3600  # 1 hour
        assert RetryHandler.get_retry_delay(4) == 7200  # 2 hours
        assert RetryHandler.get_retry_delay(5) is None  # Max retries exceeded
    
    def test_should_retry_failed_job(self, user, twitter_profile):
        """Test should_retry returns True for failed job within retry limit."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=timezone.now().date(),
            status='failed',
            scheduled_at=timezone.now(),
            retry_count=2,
            max_retries=5,
        )
        
        assert RetryHandler.should_retry(job) is True
    
    def test_should_retry_max_retries_exceeded(self, user, twitter_profile):
        """Test should_retry returns False when max retries exceeded."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=timezone.now().date(),
            status='failed',
            scheduled_at=timezone.now(),
            retry_count=5,
            max_retries=5,
        )
        
        assert RetryHandler.should_retry(job) is False
    
    def test_schedule_retry(self, user, twitter_profile):
        """Test scheduling a retry."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=timezone.now().date(),
            status='failed',
            scheduled_at=timezone.now(),
            retry_count=0,
            max_retries=5,
        )
        
        result = RetryHandler.schedule_retry(job)
        
        assert result is True
        job.refresh_from_db()
        assert job.retry_count == 1
        assert job.status == 'retrying'
        assert job.next_retry_at is not None
        # Should be approximately 5 minutes from now
        expected_time = timezone.now() + timedelta(seconds=300)
        assert abs((job.next_retry_at - expected_time).total_seconds()) < 60  # Within 1 minute
    
    def test_schedule_retry_max_exceeded(self, user, twitter_profile):
        """Test schedule_retry returns False when max retries exceeded."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=timezone.now().date(),
            status='failed',
            scheduled_at=timezone.now(),
            retry_count=5,
            max_retries=5,
        )
        
        result = RetryHandler.schedule_retry(job)
        
        assert result is False
        job.refresh_from_db()
        assert job.retry_count == 5  # Unchanged

