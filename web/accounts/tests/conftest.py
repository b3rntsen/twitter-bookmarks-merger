"""
Shared pytest configuration and fixtures.
"""
import pytest
from django.contrib.auth.models import User
from twitter.models import TwitterProfile, Tweet
from datetime import datetime


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def twitter_profile(db, user):
    """Create a test TwitterProfile."""
    profile = TwitterProfile.objects.create(
        user=user,
        twitter_username='testuser',
        twitter_user_id='12345'
    )
    profile.set_credentials('testuser', password='testpass')
    return profile


@pytest.fixture
def tweet(db, twitter_profile):
    """Create a test Tweet."""
    return Tweet.objects.create(
        tweet_id='1234567890',
        twitter_profile=twitter_profile,
        author_username='testauthor',
        author_display_name='Test Author',
        text_content='This is a test tweet',
        created_at=datetime.now(),
        is_bookmark=True
    )


# Test data factories
def create_user_fixture(**kwargs):
    """Create a User test fixture with optional overrides."""
    defaults = {
        'username': 'testuser',
        'email': 'test@example.com',
        'password': 'testpass123'
    }
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def create_twitter_profile_fixture(user=None, **kwargs):
    """Create a TwitterProfile test fixture with optional overrides."""
    if user is None:
        user = create_user_fixture()
    
    defaults = {
        'user': user,
        'twitter_username': 'testuser',
        'twitter_user_id': '12345'
    }
    defaults.update(kwargs)
    profile = TwitterProfile.objects.create(**defaults)
    profile.set_credentials('testuser', password='testpass')
    return profile


def create_tweet_fixture(twitter_profile=None, **kwargs):
    """Create a Tweet test fixture with optional overrides."""
    if twitter_profile is None:
        twitter_profile = create_twitter_profile_fixture()
    
    defaults = {
        'tweet_id': '1234567890',
        'twitter_profile': twitter_profile,
        'author_username': 'testauthor',
        'author_display_name': 'Test Author',
        'text_content': 'This is a test tweet',
        'created_at': datetime.now(),
        'is_bookmark': True
    }
    defaults.update(kwargs)
    return Tweet.objects.create(**defaults)


# Mock utilities
@pytest.fixture
def mock_twitter_scraper(mocker):
    """Mock TwitterScraper for unit testing."""
    mock_scraper = mocker.patch('twitter.services.TwitterScraper')
    mock_instance = mock_scraper.return_value
    mock_instance.get_bookmarks.return_value = [
        {
            'tweet_id': '123',
            'text_content': 'Test tweet',
            'author_username': 'testauthor',
            'created_at': '2025-01-27T12:00:00Z',
            'links': [],
            'media': []
        }
    ]
    mock_instance.login.return_value = True
    mock_instance.close.return_value = None
    return mock_instance


@pytest.fixture
def mock_media_downloader(mocker):
    """Mock MediaDownloader for unit testing."""
    mock_downloader = mocker.patch('bookmarks_app.media_handler.MediaDownloader')
    mock_instance = mock_downloader.return_value
    mock_instance.download_image.return_value = {
        'file_path': '/media/test_image.png',
        'file_size': 1024,
        'media_type': 'image',
        'success': True
    }
    mock_instance.download_video.return_value = {
        'file_path': '/media/test_video.mp4',
        'file_size': 2048,
        'media_type': 'video',
        'success': True
    }
    return mock_instance


@pytest.fixture
def mock_pdf_generator(mocker):
    """Mock PDFGenerator for unit testing."""
    mock_generator = mocker.patch('bookmarks_app.pdf_generator.PDFGenerator')
    mock_instance = mock_generator.return_value
    mock_instance.generate_pdf.return_value = {
        'pdf_path': '/media/test.pdf',
        'file_size': 4096,
        'page_count': 1,
        'success': True
    }
    return mock_instance

