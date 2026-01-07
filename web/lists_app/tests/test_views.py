"""
Tests for lists_app views.
"""
import pytest
from django.test import Client
from django.contrib.auth.models import User
from datetime import date
from twitter.models import TwitterProfile
from lists_app.models import TwitterList, Event, ListTweet
from twitter.models import Tweet


@pytest.mark.django_db
class TestListSelection:
    """Tests for list_selection view."""
    
    def test_list_selection_requires_authentication(self):
        """Test list_selection requires login."""
        client = Client()
        
        response = client.get('/lists/')
        
        assert response.status_code == 302
    
    def test_list_selection_no_twitter_profile(self, user):
        """Test list_selection redirects when no Twitter profile."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/lists/')
        
        assert response.status_code == 302
        assert 'twitter/connect' in response.url
    
    def test_list_selection_displays_lists(self, user, twitter_profile):
        """Test list_selection displays user's lists."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Test List'
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/lists/')
        
        assert response.status_code == 200
        assert 'user_lists' in response.context
        assert twitter_list in response.context['user_lists']


@pytest.mark.django_db
class TestListEvents:
    """Tests for list_events view."""
    
    def test_list_events_requires_authentication(self):
        """Test list_events requires login."""
        client = Client()
        
        response = client.get('/lists/1/events/')
        
        assert response.status_code == 302
    
    def test_list_events_not_found(self, user, twitter_profile):
        """Test list_events returns 404 for non-existent list."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/lists/999/events/')
        
        assert response.status_code == 404
    
    def test_list_events_displays_events(self, user, twitter_profile):
        """Test list_events displays events for a list."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Test List'
        )
        
        event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Test Event',
            summary='Test summary',
            tweet_count=5
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/lists/{twitter_list.id}/events/')
        
        assert response.status_code == 200
        assert 'events' in response.context
        assert event in response.context['events']
    
    def test_list_events_wrong_user(self, user, twitter_profile):
        """Test list_events denies access to other user's lists."""
        other_user = User.objects.create_user(username='other', email='other@example.com')
        other_profile = TwitterProfile.objects.create(
            user=other_user,
            twitter_username='otheruser',
            encrypted_credentials=''
        )
        other_list = TwitterList.objects.create(
            twitter_profile=other_profile,
            list_id='999',
            list_name='Other List'
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/lists/{other_list.id}/events/')
        
        assert response.status_code == 404


@pytest.mark.django_db
class TestSyncListTweets:
    """Tests for sync_list_tweets view."""
    
    def test_sync_list_tweets_requires_authentication(self):
        """Test sync_list_tweets requires login."""
        client = Client()
        
        response = client.post('/lists/1/sync/')
        
        assert response.status_code == 302
    
    def test_sync_list_tweets_not_found(self, user, twitter_profile):
        """Test sync_list_tweets returns 404 for non-existent list."""
        client = Client()
        client.force_login(user)
        
        response = client.post('/lists/999/sync/')
        
        assert response.status_code == 404
    
    def test_sync_list_tweets_starts_sync(self, user, twitter_profile):
        """Test sync_list_tweets starts background sync."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Test List'
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.post(f'/lists/{twitter_list.id}/sync/')
        
        # Should return JSON response (200) indicating sync started
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
        import json
        data = json.loads(response.content)
        assert 'status' in data or 'message' in data


@pytest.mark.django_db
class TestGenerateEvents:
    """Tests for generate_events view."""
    
    def test_generate_events_requires_authentication(self):
        """Test generate_events requires login."""
        client = Client()
        
        response = client.post('/lists/1/generate-events/')
        
        assert response.status_code == 302
    
    def test_generate_events_not_found(self, user, twitter_profile):
        """Test generate_events returns 404 for non-existent list."""
        client = Client()
        client.force_login(user)
        
        response = client.post('/lists/999/generate-events/')
        
        assert response.status_code == 404
    
    def test_generate_events_starts_generation(self, user, twitter_profile):
        """Test generate_events starts background event generation."""
        from lists_app.models import ListTweet
        from django.utils import timezone
        from datetime import date
        
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Test List'
        )
        
        # Create a tweet for today so the view doesn't return 400
        from twitter.models import Tweet
        tweet = Tweet.objects.create(
            tweet_id='123',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Test tweet',
            created_at=timezone.now(),
            is_bookmark=False
        )
        ListTweet.objects.create(
            twitter_list=twitter_list,
            tweet=tweet,
            seen_date=date.today()
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.post(f'/lists/{twitter_list.id}/generate-events/')
        
        # Should return JSON response (200) indicating generation started
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
        import json
        data = json.loads(response.content)
        assert 'success' in data or 'message' in data or 'error' in data


@pytest.mark.django_db
class TestDeleteList:
    """Tests for delete_list view."""
    
    def test_delete_list_requires_authentication(self):
        """Test delete_list requires login."""
        client = Client()
        
        response = client.post('/lists/1/delete/')
        
        assert response.status_code == 302
    
    def test_delete_list_success(self, user, twitter_profile):
        """Test delete_list deletes list."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='123456',
            list_name='Test List'
        )
        
        client = Client()
        client.force_login(user)
        
        list_id = twitter_list.id
        response = client.post(f'/lists/{list_id}/delete/')
        
        assert response.status_code == 302
        assert not TwitterList.objects.filter(id=list_id).exists()
    
    def test_delete_list_wrong_user(self, user, twitter_profile):
        """Test delete_list denies access to other user's lists."""
        other_user = User.objects.create_user(username='other', email='other@example.com')
        other_profile = TwitterProfile.objects.create(
            user=other_user,
            twitter_username='otheruser',
            encrypted_credentials=''
        )
        other_list = TwitterList.objects.create(
            twitter_profile=other_profile,
            list_id='999',
            list_name='Other List'
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.post(f'/lists/{other_list.id}/delete/')
        
        assert response.status_code == 404
        assert TwitterList.objects.filter(id=other_list.id).exists()  # Still exists

