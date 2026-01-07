"""
Integration tests for complete workflow using mocks.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date
from processing_app.models import ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot
from processing_app.schedulers import DailyScheduler
from processing_app.tasks import process_content_job
from processing_app.processors import BookmarkProcessor
from twitter.models import TwitterProfile


@pytest.mark.django_db
class TestCompleteWorkflow:
    """Integration tests for complete processing workflow."""
    
    @patch('processing_app.schedulers.async_task')
    @patch('processing_app.processors.bookmark_processor.TwitterScraperFetcher')
    @patch('processing_app.processors.bookmark_processor.BookmarkService')
    def test_schedule_to_process_to_store(self, mock_bookmark_service, mock_fetcher_class, mock_async_task, user, twitter_profile):
        """Test complete workflow: schedule -> process -> store."""
        # Setup schedule
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
        )
        
        # Schedule job
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=True)
        
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == 'pending'
        
        # Setup mocks for processing
        mock_fetcher = Mock()
        mock_fetcher.fetch_bookmarks.return_value = [
            {'tweet_id': '123', 'text_content': 'Test tweet', 'author_username': 'testuser'}
        ]
        mock_fetcher_class.return_value = mock_fetcher
        
        mock_service = Mock()
        mock_service.store_bookmarks.return_value = 1
        mock_bookmark_service.return_value = mock_service
        
        # Process job
        process_content_job(job.id)
        
        # Verify job completed
        job.refresh_from_db()
        assert job.status == 'completed'
        assert job.items_processed == 1
        
        # Verify snapshot was created/updated
        snapshot = DailyContentSnapshot.objects.filter(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today()
        ).first()
        assert snapshot is not None
        assert snapshot.bookmark_count == 1
    
    @patch('processing_app.schedulers.async_task')
    def test_schedule_creates_jobs_for_all_enabled_types(self, mock_async_task, user, twitter_profile):
        """Test scheduler creates jobs for all enabled content types."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
            process_curated_feed=True,
            process_lists=True,
        )
        
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=True)
        
        # Should create 3 jobs (one for each content type)
        assert len(jobs) == 3
        content_types = {job.content_type for job in jobs}
        assert content_types == {'bookmarks', 'curated_feed', 'lists'}
    
    @patch('processing_app.schedulers.async_task')
    def test_schedule_respects_content_type_preferences(self, mock_async_task, user, twitter_profile):
        """Test scheduler only creates jobs for enabled content types."""
        ProcessingSchedule.objects.create(
            user=user,
            enabled=True,
            process_bookmarks=True,
            process_curated_feed=False,  # Disabled
            process_lists=True,
        )
        
        scheduler = DailyScheduler()
        jobs = scheduler.schedule_user_jobs(user, immediate=True)
        
        # Should only create 2 jobs
        assert len(jobs) == 2
        content_types = {job.content_type for job in jobs}
        assert 'curated_feed' not in content_types
        assert 'bookmarks' in content_types
        assert 'lists' in content_types

