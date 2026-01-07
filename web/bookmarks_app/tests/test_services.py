"""
Tests for bookmarks_app services.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from django.utils import timezone
from twitter.models import TwitterProfile, Tweet, TweetMedia
from bookmarks_app.services import BookmarkService


@pytest.mark.django_db
class TestBookmarkService:
    """Tests for BookmarkService class."""
    
    def test_bookmark_service_initialization(self, twitter_profile):
        """Test BookmarkService can be initialized."""
        service = BookmarkService(twitter_profile)
        
        assert service.twitter_profile == twitter_profile
        assert service.media_downloader is not None
    
    def test_store_bookmarks_normal_operation(self, twitter_profile, mock_media_downloader):
        """Test store_bookmarks with valid bookmark data."""
        service = BookmarkService(twitter_profile)
        
        # Mock media downloader
        mock_media_downloader.download_media.return_value = (None, None)
        
        bookmarks = [{
            'tweet_id': '1234567890',
            'text_content': 'Test tweet',
            'author_username': 'testauthor',
            'author_display_name': 'Test Author',
            'created_at': '2025-01-27T12:00:00Z',
            'like_count': 10,
            'retweet_count': 5,
            'media_urls': []
        }]
        
        count = service.store_bookmarks(bookmarks)
        
        assert count == 1
        assert Tweet.objects.filter(tweet_id='1234567890').exists()
        tweet = Tweet.objects.get(tweet_id='1234567890')
        assert tweet.text_content == 'Test tweet'
        assert tweet.author_username == 'testauthor'
        assert tweet.is_bookmark is True
    
    def test_store_bookmarks_with_expanded_links(self, twitter_profile, mock_media_downloader):
        """Test store_bookmarks expands t.co URLs in text."""
        service = BookmarkService(twitter_profile)
        mock_media_downloader.download_media.return_value = (None, None)
        
        bookmarks = [{
            'tweet_id': '1234567890',
            'text_content': 'Check this out: https://t.co/abc123',
            'author_username': 'testauthor',
            'created_at': '2025-01-27T12:00:00Z',
            'links': [{
                'tco_url': 'https://t.co/abc123',
                'expanded_url': 'https://example.com/article'
            }],
            'media_urls': []
        }]
        
        service.store_bookmarks(bookmarks)
        
        tweet = Tweet.objects.get(tweet_id='1234567890')
        assert 'https://example.com/article' in tweet.text_content
        assert 'https://t.co/abc123' not in tweet.text_content
    
    def test_store_bookmarks_duplicate_tweet(self, twitter_profile, mock_media_downloader):
        """Test store_bookmarks handles duplicate tweets."""
        service = BookmarkService(twitter_profile)
        mock_media_downloader.download_media.return_value = (None, None)
        
        # Create existing tweet
        Tweet.objects.create(
            tweet_id='1234567890',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Original tweet',
            created_at=timezone.now()
        )
        
        bookmarks = [{
            'tweet_id': '1234567890',
            'text_content': 'Updated tweet',
            'author_username': 'testauthor',
            'created_at': '2025-01-27T12:00:00Z',
            'media_urls': []
        }]
        
        count = service.store_bookmarks(bookmarks)
        
        # Should not create new tweet, but should update
        assert count == 0
        assert Tweet.objects.filter(tweet_id='1234567890').count() == 1
        tweet = Tweet.objects.get(tweet_id='1234567890')
        assert tweet.text_content == 'Updated tweet'
    
    @patch('bookmarks_app.services.MediaDownloader')
    def test_store_bookmarks_with_media(self, mock_downloader_class, twitter_profile):
        """Test store_bookmarks downloads and stores media."""
        # Setup mock
        mock_downloader_instance = MagicMock()
        mock_downloader_class.return_value = mock_downloader_instance
        mock_downloader_instance.download_media.return_value = (
            'tweets/1234567890/image.png',
            'tweets/1234567890/thumb.png'
        )
        mock_downloader_instance.get_file_size.return_value = 1024
        
        service = BookmarkService(twitter_profile)
        
        bookmarks = [{
            'tweet_id': '1234567890',
            'text_content': 'Test tweet with image',
            'author_username': 'testauthor',
            'created_at': '2025-01-27T12:00:00Z',
            'media_urls': ['https://example.com/image.png']
        }]
        
        service.store_bookmarks(bookmarks)
        
        tweet = Tweet.objects.get(tweet_id='1234567890')
        assert TweetMedia.objects.filter(tweet=tweet).exists()
        media = TweetMedia.objects.get(tweet=tweet)
        assert media.media_type == 'image'
        assert 'image.png' in media.file_path
    
    def test_store_bookmarks_empty_list(self, twitter_profile):
        """Test store_bookmarks with empty list."""
        service = BookmarkService(twitter_profile)
        
        count = service.store_bookmarks([])
        
        assert count == 0
    
    def test_store_bookmarks_invalid_data(self, twitter_profile, mock_media_downloader):
        """Test store_bookmarks handles invalid bookmark data gracefully."""
        service = BookmarkService(twitter_profile)
        mock_media_downloader.download_media.return_value = (None, None)
        
        # Missing required tweet_id
        bookmarks = [{
            'text_content': 'Invalid tweet',
            'author_username': 'testauthor'
        }]
        
        # Should not raise exception, just skip invalid entries
        count = service.store_bookmarks(bookmarks)
        assert count == 0
    
    def test_store_bookmarks_updates_sync_timestamp(self, twitter_profile, mock_media_downloader):
        """Test store_bookmarks updates twitter_profile.last_sync_at."""
        service = BookmarkService(twitter_profile)
        mock_media_downloader.download_media.return_value = (None, None)
        
        initial_sync_time = twitter_profile.last_sync_at
        
        bookmarks = [{
            'tweet_id': '1234567890',
            'text_content': 'Test tweet',
            'author_username': 'testauthor',
            'created_at': '2025-01-27T12:00:00Z',
            'media_urls': []
        }]
        
        service.store_bookmarks(bookmarks)
        
        twitter_profile.refresh_from_db()
        assert twitter_profile.last_sync_at is not None
        assert twitter_profile.last_sync_at != initial_sync_time
    
    def test_parse_timestamp_iso_format(self, twitter_profile):
        """Test _parse_timestamp with ISO format."""
        service = BookmarkService(twitter_profile)
        
        timestamp = service._parse_timestamp('2025-01-27T12:00:00Z')
        assert isinstance(timestamp, datetime)
    
    def test_parse_timestamp_invalid_format(self, twitter_profile):
        """Test _parse_timestamp with invalid format returns current time."""
        service = BookmarkService(twitter_profile)
        
        timestamp = service._parse_timestamp('invalid-date')
        assert isinstance(timestamp, datetime)
    
    def test_parse_timestamp_empty_string(self, twitter_profile):
        """Test _parse_timestamp with empty string returns current time."""
        service = BookmarkService(twitter_profile)
        
        timestamp = service._parse_timestamp('')
        assert isinstance(timestamp, datetime)

