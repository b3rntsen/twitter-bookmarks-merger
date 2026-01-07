"""
Tests for twitter models.
"""
import pytest
from django.contrib.auth.models import User
from datetime import datetime
from twitter.models import TwitterProfile, Tweet, TweetThread, TweetMedia, TweetReply


@pytest.mark.django_db
class TestTwitterProfile:
    """Tests for TwitterProfile model."""
    
    def test_twitter_profile_creation(self, user):
        """Test TwitterProfile can be created with valid data."""
        profile = TwitterProfile.objects.create(
            user=user,
            twitter_username='testuser',
            twitter_user_id='123456',
            encrypted_credentials='encrypted_data',
            sync_status='pending'
        )
        
        assert profile.user == user
        assert profile.twitter_username == 'testuser'
        assert profile.twitter_user_id == '123456'
        assert profile.sync_status == 'pending'
        assert profile.created_at is not None
        assert profile.updated_at is not None
    
    def test_twitter_profile_set_credentials(self, user):
        """Test TwitterProfile.set_credentials encrypts credentials."""
        profile = TwitterProfile.objects.create(
            user=user,
            twitter_username='testuser',
            encrypted_credentials=''
        )
        
        profile.set_credentials('testuser', password='testpass', cookies={'session': 'abc123'})
        
        assert profile.encrypted_credentials is not None
        assert profile.encrypted_credentials != ''
        assert 'testuser' not in profile.encrypted_credentials  # Should be encrypted
    
    def test_twitter_profile_get_credentials(self, user):
        """Test TwitterProfile.get_credentials decrypts credentials."""
        profile = TwitterProfile.objects.create(
            user=user,
            twitter_username='testuser',
            encrypted_credentials=''
        )
        
        profile.set_credentials('testuser', password='testpass', cookies={'session': 'abc123'})
        credentials = profile.get_credentials()
        
        assert credentials is not None
        assert credentials['username'] == 'testuser'
        assert credentials['password'] == 'testpass'
        assert credentials['cookies'] == {'session': 'abc123'}
    
    def test_twitter_profile_get_credentials_empty(self, user):
        """Test TwitterProfile.get_credentials returns None when empty."""
        profile = TwitterProfile.objects.create(
            user=user,
            twitter_username='testuser',
            encrypted_credentials=''
        )
        
        credentials = profile.get_credentials()
        assert credentials is None
    
    def test_twitter_profile_str_representation(self, user):
        """Test TwitterProfile string representation."""
        profile = TwitterProfile.objects.create(
            user=user,
            twitter_username='testuser',
            encrypted_credentials=''
        )
        
        assert user.email in str(profile)
        assert 'testuser' in str(profile)


@pytest.mark.django_db
class TestTweet:
    """Tests for Tweet model."""
    
    def test_tweet_creation(self, twitter_profile):
        """Test Tweet can be created with valid data."""
        tweet = Tweet.objects.create(
            tweet_id='1234567890',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            author_display_name='Test Author',
            text_content='This is a test tweet',
            created_at=datetime.now(),
            is_bookmark=True
        )
        
        assert tweet.tweet_id == '1234567890'
        assert tweet.twitter_profile == twitter_profile
        assert tweet.author_username == 'testauthor'
        assert tweet.text_content == 'This is a test tweet'
        assert tweet.is_bookmark is True
        assert tweet.created_at is not None
    
    def test_tweet_unique_tweet_id(self, twitter_profile):
        """Test Tweet tweet_id must be unique."""
        Tweet.objects.create(
            tweet_id='1234567890',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='First tweet',
            created_at=datetime.now()
        )
        
        # Creating another tweet with same tweet_id should fail
        with pytest.raises(Exception):  # IntegrityError
            Tweet.objects.create(
                tweet_id='1234567890',
                twitter_profile=twitter_profile,
                author_username='testauthor2',
                text_content='Second tweet',
                created_at=datetime.now()
            )
    
    def test_tweet_str_representation(self, twitter_profile):
        """Test Tweet string representation."""
        tweet = Tweet.objects.create(
            tweet_id='1234567890',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='This is a test tweet with more than 50 characters to test truncation',
            created_at=datetime.now()
        )
        
        assert 'testauthor' in str(tweet)
        assert 'This is a test tweet with more than 50' in str(tweet)
        assert str(tweet).endswith('...')


@pytest.mark.django_db
class TestTweetThread:
    """Tests for TweetThread model."""
    
    def test_tweet_thread_creation(self, twitter_profile):
        """Test TweetThread can be created with valid data."""
        parent = Tweet.objects.create(
            tweet_id='111',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Parent tweet',
            created_at=datetime.now()
        )
        child = Tweet.objects.create(
            tweet_id='222',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Child tweet',
            created_at=datetime.now()
        )
        
        thread = TweetThread.objects.create(
            parent_tweet=parent,
            child_tweet=child,
            thread_order=1
        )
        
        assert thread.parent_tweet == parent
        assert thread.child_tweet == child
        assert thread.thread_order == 1
        assert thread.created_at is not None
    
    def test_tweet_thread_unique_together(self, twitter_profile):
        """Test TweetThread unique_together constraint."""
        parent = Tweet.objects.create(
            tweet_id='111',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Parent tweet',
            created_at=datetime.now()
        )
        child = Tweet.objects.create(
            tweet_id='222',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Child tweet',
            created_at=datetime.now()
        )
        
        TweetThread.objects.create(
            parent_tweet=parent,
            child_tweet=child
        )
        
        # Creating another thread with same parent and child should fail
        with pytest.raises(Exception):  # IntegrityError
            TweetThread.objects.create(
                parent_tweet=parent,
                child_tweet=child
            )


@pytest.mark.django_db
class TestTweetMedia:
    """Tests for TweetMedia model."""
    
    def test_tweet_media_creation(self, twitter_profile, tweet):
        """Test TweetMedia can be created with valid data."""
        media = TweetMedia.objects.create(
            tweet=tweet,
            media_type='image',
            file_path='/media/image.png',
            original_url='https://example.com/image.png',
            thumbnail_path='/media/thumb.png',
            file_size=1024
        )
        
        assert media.tweet == tweet
        assert media.media_type == 'image'
        assert media.file_path == '/media/image.png'
        assert media.original_url == 'https://example.com/image.png'
        assert media.file_size == 1024
        assert media.created_at is not None
    
    def test_tweet_media_str_representation(self, tweet):
        """Test TweetMedia string representation."""
        media = TweetMedia.objects.create(
            tweet=tweet,
            media_type='image',
            file_path='/media/image.png',
            original_url='https://example.com/image.png'
        )
        
        assert 'image' in str(media)
        assert tweet.tweet_id in str(media)


@pytest.mark.django_db
class TestTweetReply:
    """Tests for TweetReply model."""
    
    def test_tweet_reply_creation(self, twitter_profile):
        """Test TweetReply can be created with valid data."""
        original = Tweet.objects.create(
            tweet_id='111',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Original tweet',
            created_at=datetime.now()
        )
        reply = Tweet.objects.create(
            tweet_id='222',
            twitter_profile=twitter_profile,
            author_username='replyauthor',
            text_content='Reply tweet',
            created_at=datetime.now()
        )
        
        tweet_reply = TweetReply.objects.create(
            original_tweet=original,
            reply_tweet=reply,
            reply_author_username='replyauthor',
            reply_author_id='999'
        )
        
        assert tweet_reply.original_tweet == original
        assert tweet_reply.reply_tweet == reply
        assert tweet_reply.reply_author_username == 'replyauthor'
        assert tweet_reply.created_at is not None
    
    def test_tweet_reply_unique_together(self, twitter_profile):
        """Test TweetReply unique_together constraint."""
        original = Tweet.objects.create(
            tweet_id='111',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Original tweet',
            created_at=datetime.now()
        )
        reply = Tweet.objects.create(
            tweet_id='222',
            twitter_profile=twitter_profile,
            author_username='replyauthor',
            text_content='Reply tweet',
            created_at=datetime.now()
        )
        
        TweetReply.objects.create(
            original_tweet=original,
            reply_tweet=reply,
            reply_author_username='replyauthor'
        )
        
        # Creating another reply with same original and reply should fail
        with pytest.raises(Exception):  # IntegrityError
            TweetReply.objects.create(
                original_tweet=original,
                reply_tweet=reply,
                reply_author_username='replyauthor2'
            )

