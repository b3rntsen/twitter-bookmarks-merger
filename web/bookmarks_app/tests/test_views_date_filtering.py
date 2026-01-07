"""
Tests for date filtering in bookmarks_app views.
"""
import pytest
from django.test import Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from twitter.models import TwitterProfile, Tweet
from processing_app.models import DailyContentSnapshot


@pytest.mark.django_db
class TestBookmarkListDateFiltering:
    """Tests for bookmark_list view date filtering."""
    
    def test_bookmark_list_defaults_to_today(self, user, twitter_profile):
        """Test bookmark_list defaults to today's content."""
        # Create bookmark for today
        today_bookmark = Tweet.objects.create(
            twitter_profile=twitter_profile,
            tweet_id='today_123',
            author_username='testuser',
            text_content='Today tweet',
            created_at=timezone.now(),
            is_bookmark=True,
            processing_date=date.today(),
        )
        
        # Create bookmark for yesterday
        yesterday = date.today() - timedelta(days=1)
        yesterday_bookmark = Tweet.objects.create(
            twitter_profile=twitter_profile,
            tweet_id='yesterday_123',
            author_username='testuser',
            text_content='Yesterday tweet',
            created_at=timezone.now() - timedelta(days=1),
            is_bookmark=True,
            processing_date=yesterday,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/')
        
        assert response.status_code == 200
        bookmarks = response.context['bookmarks']
        assert today_bookmark in bookmarks
        assert yesterday_bookmark not in bookmarks
    
    def test_bookmark_list_filters_by_date_parameter(self, user, twitter_profile):
        """Test bookmark_list filters by date query parameter."""
        yesterday = date.today() - timedelta(days=1)
        
        # Create bookmark for yesterday
        yesterday_bookmark = Tweet.objects.create(
            twitter_profile=twitter_profile,
            tweet_id='yesterday_123',
            author_username='testuser',
            text_content='Yesterday tweet',
            created_at=timezone.now() - timedelta(days=1),
            is_bookmark=True,
            processing_date=yesterday,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/?date={yesterday}')
        
        assert response.status_code == 200
        bookmarks = response.context['bookmarks']
        assert yesterday_bookmark in bookmarks
        assert response.context['filter_date'] == yesterday


@pytest.mark.django_db
class TestCuratedFeedDateFiltering:
    """Tests for curated_feed view date filtering."""
    
    def test_curated_feed_defaults_to_today(self, user, twitter_profile):
        """Test curated_feed defaults to today's content."""
        from bookmarks_app.models import CuratedFeed
        
        # Create feed for today
        today_feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=date.today(),
            num_tweets_fetched=10,
        )
        
        # Create feed for yesterday
        yesterday = date.today() - timedelta(days=1)
        yesterday_feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=yesterday,
            num_tweets_fetched=5,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/curated-feed/')
        
        assert response.status_code == 200
        assert response.context['latest_feed'] == today_feed
        assert response.context['latest_feed'] != yesterday_feed
    
    def test_curated_feed_filters_by_date_parameter(self, user, twitter_profile):
        """Test curated_feed filters by date query parameter."""
        from bookmarks_app.models import CuratedFeed
        
        yesterday = date.today() - timedelta(days=1)
        
        yesterday_feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            processing_date=yesterday,
            num_tweets_fetched=5,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/curated-feed/?date={yesterday}')
        
        assert response.status_code == 200
        assert response.context['latest_feed'] == yesterday_feed
        assert response.context['filter_date'] == yesterday
    
    def test_curated_feed_no_fetch_button(self, user, twitter_profile):
        """Test curated_feed template has no fetch button."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/curated-feed/')
        
        assert response.status_code == 200
        # Check that fetch button URL is not in response
        assert 'fetch_curated_feed' not in response.content.decode()

