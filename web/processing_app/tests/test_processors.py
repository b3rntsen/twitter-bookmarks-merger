"""
Tests for processing_app processors.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date
from processing_app.models import ContentProcessingJob
from processing_app.processors import (
    BookmarkProcessor,
    CuratedFeedProcessor,
    ListProcessor,
    ProcessingError,
    CredentialError,
    ValidationError
)
from processing_app.fetchers import TwitterScraperFetcher, FetcherError
from twitter.models import TwitterProfile, Tweet
from bookmarks_app.models import CuratedFeed


@pytest.mark.django_db
class TestBaseProcessor:
    """Tests for BaseProcessor interface."""
    
    def test_get_retry_delays(self):
        """Test retry delays are correct."""
        processor = BookmarkProcessor()
        delays = processor.get_retry_delays()
        
        assert delays == [300, 900, 1800, 3600, 7200]  # 5min, 15min, 30min, 1h, 2h


@pytest.mark.django_db
class TestBookmarkProcessor:
    """Tests for BookmarkProcessor."""
    
    def test_validate_job_success(self, user, twitter_profile):
        """Test job validation succeeds for valid job."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = BookmarkProcessor()
        assert processor.validate_job(job) is True
    
    def test_validate_job_wrong_content_type(self, user, twitter_profile):
        """Test job validation fails for wrong content type."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='curated_feed',  # Wrong type
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = BookmarkProcessor()
        assert processor.validate_job(job) is False
    
    def test_validate_job_future_date(self, user, twitter_profile):
        """Test job validation fails for future date."""
        from datetime import timedelta
        future_date = date.today() + timedelta(days=1)
        
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=future_date,
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = BookmarkProcessor()
        assert processor.validate_job(job) is False
    
    @patch('processing_app.processors.bookmark_processor.TwitterScraperFetcher')
    @patch('processing_app.processors.bookmark_processor.BookmarkService')
    def test_process_bookmarks_success(self, mock_bookmark_service, mock_fetcher_class, user, twitter_profile):
        """Test successful bookmark processing."""
        # Setup mocks
        mock_fetcher = Mock()
        mock_fetcher.fetch_bookmarks.return_value = [
            {'tweet_id': '123', 'text_content': 'Test tweet', 'author_username': 'testuser'}
        ]
        mock_fetcher_class.return_value = mock_fetcher
        
        mock_service = Mock()
        mock_service.store_bookmarks.return_value = 1
        mock_bookmark_service.return_value = mock_service
        
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = BookmarkProcessor()
        result = processor.process(job)
        
        assert result['success'] is True
        assert result['items_processed'] == 1
        job.refresh_from_db()
        assert job.status == 'completed'
        assert job.items_processed == 1
    
    @patch('processing_app.processors.bookmark_processor.TwitterScraperFetcher')
    def test_process_bookmarks_credential_error(self, mock_fetcher_class, user, twitter_profile):
        """Test processing handles credential errors."""
        mock_fetcher = Mock()
        mock_fetcher.fetch_bookmarks.side_effect = CredentialError("Invalid credentials")
        mock_fetcher_class.return_value = mock_fetcher
        
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='bookmarks',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = BookmarkProcessor()
        
        with pytest.raises(CredentialError):
            processor.process(job)
        
        job.refresh_from_db()
        assert job.status == 'failed'


@pytest.mark.django_db
class TestCuratedFeedProcessor:
    """Tests for CuratedFeedProcessor."""
    
    def test_validate_job_success(self, user, twitter_profile):
        """Test job validation succeeds for valid job."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='curated_feed',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = CuratedFeedProcessor()
        assert processor.validate_job(job) is True
    
    @patch('processing_app.processors.curated_feed_processor.TwitterScraperFetcher')
    @patch('processing_app.processors.curated_feed_processor.TweetCategorizationService')
    def test_process_curated_feed_success(self, mock_categorization, mock_fetcher_class, user, twitter_profile):
        """Test successful curated feed processing."""
        # Setup mocks
        mock_fetcher = Mock()
        mock_fetcher.fetch_home_timeline.return_value = [
            {'tweet_id': '123', 'text_content': 'Test tweet', 'author_username': 'testuser'}
        ]
        mock_fetcher_class.return_value = mock_fetcher
        
        mock_cat_service = Mock()
        mock_cat_service.categorize_tweets.return_value = {
            'Category1': [{'tweet_id': '123', 'text_content': 'Test tweet'}]
        }
        mock_categorization.return_value = mock_cat_service
        
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='curated_feed',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = CuratedFeedProcessor()
        result = processor.process(job)
        
        assert result['success'] is True
        assert result['items_processed'] == 1
        job.refresh_from_db()
        assert job.status == 'completed'
        
        # Check CuratedFeed was created
        assert CuratedFeed.objects.filter(user=user, processing_date=date.today()).exists()


@pytest.mark.django_db
class TestListProcessor:
    """Tests for ListProcessor."""
    
    def test_validate_job_success(self, user, twitter_profile):
        """Test job validation succeeds when user has lists."""
        from lists_app.models import TwitterList
        
        # Create a list for the user
        TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='test_list_123',
            list_name='Test List'
        )
        
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='lists',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = ListProcessor()
        assert processor.validate_job(job) is True
    
    def test_validate_job_no_lists(self, user, twitter_profile):
        """Test job validation fails when user has no lists."""
        job = ContentProcessingJob.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            content_type='lists',
            processing_date=date.today(),
            status='pending',
            scheduled_at=timezone.now(),
        )
        
        processor = ListProcessor()
        assert processor.validate_job(job) is False

