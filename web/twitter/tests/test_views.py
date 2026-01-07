"""
Tests for twitter views.
"""
import pytest
from django.test import Client
from django.contrib.auth.models import User
from twitter.models import TwitterProfile


@pytest.mark.django_db
class TestConnectTwitter:
    """Tests for connect_twitter view."""
    
    def test_connect_twitter_requires_authentication(self):
        """Test connect_twitter requires login."""
        client = Client()
        
        response = client.get('/twitter/connect/')
        
        assert response.status_code == 302
    
    def test_connect_twitter_get(self, user):
        """Test connect_twitter displays form."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/twitter/connect/')
        
        assert response.status_code == 200
        assert 'form' in response.context
    
    def test_connect_twitter_post_success(self, user):
        """Test connect_twitter creates Twitter profile."""
        client = Client()
        client.force_login(user)
        
        response = client.post('/twitter/connect/', {
            'username': 'testuser',
            'password': 'testpass',
            'use_cookies': False
        })
        
        assert response.status_code == 302  # Redirect after success
        assert TwitterProfile.objects.filter(user=user, twitter_username='testuser').exists()
    
    def test_connect_twitter_post_with_cookies(self, user):
        """Test connect_twitter accepts cookies."""
        client = Client()
        client.force_login(user)
        
        cookies_json = '{"session": "abc123"}'
        response = client.post('/twitter/connect/', {
            'username': 'testuser',
            'use_cookies': True,
            'cookies_json': cookies_json
        })
        
        assert response.status_code == 302
        profile = TwitterProfile.objects.get(user=user, twitter_username='testuser')
        credentials = profile.get_credentials()
        assert credentials is not None
        assert credentials.get('cookies') == {'session': 'abc123'}
    
    def test_connect_twitter_post_invalid_cookies(self, user):
        """Test connect_twitter handles invalid JSON cookies."""
        client = Client()
        client.force_login(user)
        
        response = client.post('/twitter/connect/', {
            'username': 'testuser',
            'use_cookies': True,
            'cookies_json': 'invalid json'
        })
        
        assert response.status_code == 200  # Returns form with error
        assert 'form' in response.context
        assert not TwitterProfile.objects.filter(user=user).exists()


@pytest.mark.django_db
class TestDisconnectTwitter:
    """Tests for disconnect_twitter view."""
    
    def test_disconnect_twitter_requires_authentication(self):
        """Test disconnect_twitter requires login."""
        client = Client()
        
        response = client.get('/twitter/disconnect/')
        
        assert response.status_code == 302
    
    def test_disconnect_twitter_get(self, user, twitter_profile):
        """Test disconnect_twitter displays confirmation."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/twitter/disconnect/')
        
        assert response.status_code == 200
        assert 'profile' in response.context
    
    def test_disconnect_twitter_post_success(self, user, twitter_profile):
        """Test disconnect_twitter deletes profile."""
        client = Client()
        client.force_login(user)
        
        username = twitter_profile.twitter_username
        response = client.post('/twitter/disconnect/')
        
        assert response.status_code == 302
        assert not TwitterProfile.objects.filter(user=user, twitter_username=username).exists()
    
    def test_disconnect_twitter_no_profile(self, user):
        """Test disconnect_twitter returns 404 when no profile."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/twitter/disconnect/')
        
        assert response.status_code == 404


@pytest.mark.django_db
class TestSyncBookmarks:
    """Tests for sync_bookmarks view."""
    
    def test_sync_bookmarks_requires_authentication(self):
        """Test sync_bookmarks requires login."""
        client = Client()
        
        response = client.get('/twitter/sync/')
        
        assert response.status_code == 302
    
    def test_sync_bookmarks_no_profile(self, user):
        """Test sync_bookmarks redirects when no Twitter profile."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/twitter/sync/')
        
        assert response.status_code == 302
        assert 'twitter/connect' in response.url
    
    def test_sync_bookmarks_displays_status(self, user, twitter_profile):
        """Test sync_bookmarks displays sync status."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/twitter/sync/')
        
        assert response.status_code == 200
        assert 'profile' in response.context
    
    def test_sync_bookmarks_post_starts_sync(self, user, twitter_profile):
        """Test sync_bookmarks POST starts background sync."""
        client = Client()
        client.force_login(user)
        
        response = client.post('/twitter/sync/', {
            'max_bookmarks': '10',
            'use_twikit': 'false'
        })
        
        # Should redirect after starting sync
        assert response.status_code == 302
        twitter_profile.refresh_from_db()
        # Status may be pending or error depending on credentials
        assert twitter_profile.sync_status in ['pending', 'error', 'success']

