"""
Tests for bookmarks_app models.
"""
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from twitter.models import TwitterProfile, Tweet
from bookmarks_app.models import CuratedFeed, TweetCategory, CategorizedTweet
from datetime import datetime


@pytest.mark.django_db
class TestCuratedFeed:
    """Tests for CuratedFeed model."""
    
    def test_curated_feed_creation(self, user, twitter_profile):
        """Test CuratedFeed can be created with valid data."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            num_tweets_fetched=10,
            num_categories=3,
            config_num_tweets=100
        )
        
        assert feed.user == user
        assert feed.twitter_profile == twitter_profile
        assert feed.num_tweets_fetched == 10
        assert feed.num_categories == 3
        assert feed.config_num_tweets == 100
        assert feed.created_at is not None
    
    def test_curated_feed_str_representation(self, user, twitter_profile):
        """Test CuratedFeed string representation."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        
        assert str(feed) == f"Curated Feed for {user.username} - {feed.created_at}"
    
    def test_curated_feed_ordering(self, user, twitter_profile):
        """Test CuratedFeed ordering by created_at descending."""
        feed1 = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        feed2 = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        
        feeds = list(CuratedFeed.objects.all())
        assert feeds[0] == feed2  # Most recent first
        assert feeds[1] == feed1


@pytest.mark.django_db
class TestTweetCategory:
    """Tests for TweetCategory model."""
    
    def test_tweet_category_creation(self, user, twitter_profile):
        """Test TweetCategory can be created with valid data."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        
        category = TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology',
            description='Tech-related tweets',
            summary='AI-generated summary'
        )
        
        assert category.curated_feed == feed
        assert category.name == 'Technology'
        assert category.description == 'Tech-related tweets'
        assert category.summary == 'AI-generated summary'
        assert category.created_at is not None
    
    def test_tweet_category_unique_together(self, user, twitter_profile):
        """Test TweetCategory unique_together constraint."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        
        TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology'
        )
        
        # Creating another category with same name should fail
        with pytest.raises(Exception):  # IntegrityError or ValidationError
            TweetCategory.objects.create(
                curated_feed=feed,
                name='Technology'
            )
    
    def test_tweet_category_str_representation(self, user, twitter_profile):
        """Test TweetCategory string representation."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        category = TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology'
        )
        
        assert 'Technology' in str(category)
        assert str(feed) in str(category)


@pytest.mark.django_db
class TestCategorizedTweet:
    """Tests for CategorizedTweet model."""
    
    def test_categorized_tweet_creation(self, user, twitter_profile, tweet):
        """Test CategorizedTweet can be created with valid data."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        category = TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology'
        )
        
        categorized = CategorizedTweet.objects.create(
            category=category,
            tweet=tweet
        )
        
        assert categorized.category == category
        assert categorized.tweet == tweet
        assert categorized.created_at is not None
    
    def test_categorized_tweet_unique_together(self, user, twitter_profile, tweet):
        """Test CategorizedTweet unique_together constraint."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        category = TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology'
        )
        
        CategorizedTweet.objects.create(
            category=category,
            tweet=tweet
        )
        
        # Creating another with same category and tweet should fail
        with pytest.raises(Exception):  # IntegrityError or ValidationError
            CategorizedTweet.objects.create(
                category=category,
                tweet=tweet
            )
    
    def test_categorized_tweet_str_representation(self, user, twitter_profile, tweet):
        """Test CategorizedTweet string representation."""
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile
        )
        category = TweetCategory.objects.create(
            curated_feed=feed,
            name='Technology'
        )
        categorized = CategorizedTweet.objects.create(
            category=category,
            tweet=tweet
        )
        
        str_repr = str(categorized)
        assert 'Technology' in str_repr
        assert '@testauthor' in str_repr or tweet.author_username in str_repr

