"""
Tests for lists_app models.
"""
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from datetime import date, datetime
from twitter.models import TwitterProfile, Tweet
from lists_app.models import TwitterList, ListTweet, Event, EventTweet


@pytest.mark.django_db
class TestTwitterList:
    """Tests for TwitterList model."""
    
    def test_twitter_list_creation(self, twitter_profile):
        """Test TwitterList can be created with valid data."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News',
            list_slug='tech-news',
            list_url='https://twitter.com/i/lists/123456',
            description='Technology news list',
            member_count=100,
            subscriber_count=50
        )
        
        assert twitter_list.twitter_profile == twitter_profile
        assert twitter_list.list_id == '123456'
        assert twitter_list.list_name == 'Tech News'
        assert twitter_list.member_count == 100
        assert twitter_list.subscriber_count == 50
        assert twitter_list.created_at is not None
        assert twitter_list.updated_at is not None
    
    def test_twitter_list_unique_together(self, twitter_profile):
        """Test TwitterList unique_together constraint."""
        TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        
        # Creating another list with same profile and list_id should fail
        with pytest.raises(Exception):  # IntegrityError or ValidationError
            TwitterList.objects.create(
                twitter_profile=twitter_profile,
                list_id='123456',
                list_name='Different Name'
            )
    
    def test_twitter_list_str_representation(self, twitter_profile):
        """Test TwitterList string representation."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        
        assert 'Tech News' in str(twitter_list)
        assert twitter_profile.twitter_username in str(twitter_list)


@pytest.mark.django_db
class TestListTweet:
    """Tests for ListTweet model."""
    
    def test_list_tweet_creation(self, twitter_profile, tweet):
        """Test ListTweet can be created with valid data."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        
        list_tweet = ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        
        assert list_tweet.twitter_list == twitter_list
        assert list_tweet.tweet == tweet
        assert list_tweet.seen_date == date.today()
        assert list_tweet.created_at is not None
    
    def test_list_tweet_unique_together(self, twitter_profile, tweet):
        """Test ListTweet unique_together constraint."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        seen_date = date.today()
        
        ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=seen_date
        )
        
        # Creating another with same list, tweet, and date should fail
        with pytest.raises(Exception):  # IntegrityError or ValidationError
            ListTweet.objects.create(
                twitter_list=twitter_list,
                tweet=tweet,
                seen_date=seen_date
            )
    
    def test_list_tweet_str_representation(self, twitter_profile, tweet):
        """Test ListTweet string representation."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        list_tweet = ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        
        assert 'Tech News' in str(list_tweet)
        assert tweet.tweet_id in str(list_tweet)


@pytest.mark.django_db
class TestEvent:
    """Tests for Event model."""
    
    def test_event_creation(self, twitter_profile):
        """Test Event can be created with valid data."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Major Tech Announcement',
            summary='AI-generated summary of the event',
            tweet_count=10,
            keywords=['tech', 'AI', 'announcement']
        )
        
        assert event.twitter_list == twitter_list
        assert event.event_date == date.today()
        assert event.headline == 'Major Tech Announcement'
        assert event.tweet_count == 10
        assert event.keywords == ['tech', 'AI', 'announcement']
        assert event.created_at is not None
        assert event.updated_at is not None
    
    def test_event_str_representation(self, twitter_profile):
        """Test Event string representation."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Major Tech Announcement',
            summary='Summary'
        )
        
        assert 'Major Tech Announcement' in str(event)
        assert str(date.today()) in str(event)


@pytest.mark.django_db
class TestEventTweet:
    """Tests for EventTweet model."""
    
    def test_event_tweet_creation(self, twitter_profile, tweet):
        """Test EventTweet can be created with valid data."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        list_tweet = ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Major Tech Announcement',
            summary='Summary'
        )
        
        event_tweet = EventTweet.objects.create(
            event=event,
            list_tweet=list_tweet,
            relevance_score=0.95
        )
        
        assert event_tweet.event == event
        assert event_tweet.list_tweet == list_tweet
        assert event_tweet.relevance_score == 0.95
        assert event_tweet.created_at is not None
    
    def test_event_tweet_unique_together(self, twitter_profile, tweet):
        """Test EventTweet unique_together constraint."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        list_tweet = ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Major Tech Announcement',
            summary='Summary'
        )
        
        EventTweet.objects.create(
            event=event,
            list_tweet=list_tweet,
            relevance_score=0.95
        )
        
        # Creating another with same event and list_tweet should fail
        with pytest.raises(Exception):  # IntegrityError or ValidationError
            EventTweet.objects.create(
                event=event,
                list_tweet=list_tweet,
                relevance_score=0.80
            )
    
    def test_event_tweet_str_representation(self, twitter_profile, tweet):
        """Test EventTweet string representation."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Tech News'
        )
        list_tweet = ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Major Tech Announcement',
            summary='Summary'
        )
        event_tweet = EventTweet.objects.create(
            event=event,
            list_tweet=list_tweet
        )
        
        assert 'Major Tech Announcement' in str(event_tweet)
        assert tweet.tweet_id in str(event_tweet)

