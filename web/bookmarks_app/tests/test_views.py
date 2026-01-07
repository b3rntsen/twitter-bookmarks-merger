"""
Tests for bookmarks_app views.
"""
import pytest
from unittest.mock import patch, MagicMock
from django.test import Client
from django.contrib.auth.models import User
from django.urls import reverse
from twitter.models import TwitterProfile, Tweet
from datetime import datetime


@pytest.mark.django_db
class TestBookmarkList:
    """Tests for bookmark_list view."""
    
    def test_bookmark_list_requires_authentication(self):
        """Test bookmark_list requires login."""
        client = Client()
        
        response = client.get('/')
        
        assert response.status_code == 302  # Redirect to login
        assert '/accounts/login' in response.url
    
    def test_bookmark_list_no_twitter_profile(self, user):
        """Test bookmark_list redirects when no Twitter profile."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/')
        
        assert response.status_code == 302  # Redirect to connect
        assert 'twitter/connect' in response.url
    
    def test_bookmark_list_with_bookmarks(self, user, twitter_profile, tweet):
        """Test bookmark_list displays bookmarks."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/')
        
        assert response.status_code == 200
        assert 'bookmarks' in response.context
        assert tweet in response.context['bookmarks']
    
    def test_bookmark_list_search(self, user, twitter_profile, tweet):
        """Test bookmark_list filters by search query."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/', {'search': tweet.text_content[:10]})
        
        assert response.status_code == 200
        assert 'bookmarks' in response.context
        assert tweet in response.context['bookmarks']
    
    def test_bookmark_list_author_filter(self, user, twitter_profile, tweet):
        """Test bookmark_list filters by author."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/', {'author': tweet.author_username})
        
        assert response.status_code == 200
        assert 'bookmarks' in response.context
        assert tweet in response.context['bookmarks']
    
    def test_bookmark_list_pagination(self, user, twitter_profile):
        """Test bookmark_list paginates results."""
        from django.utils import timezone
        # Create multiple bookmarks
        for i in range(25):
            Tweet.objects.create(
                tweet_id=f'123{i}',
                twitter_profile=twitter_profile,
                author_username='testauthor',
                text_content=f'Tweet {i}',
                created_at=timezone.now(),
                is_bookmark=True
            )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/')
        
        assert response.status_code == 200
        assert response.context['page_obj'].paginator.num_pages > 1


@pytest.mark.django_db
class TestBookmarkDetail:
    """Tests for bookmark_detail view."""
    
    def test_bookmark_detail_requires_authentication(self, tweet):
        """Test bookmark_detail requires login."""
        client = Client()
        
        response = client.get(f'/bookmark/{tweet.tweet_id}/')
        
        assert response.status_code == 302
    
    def test_bookmark_detail_not_found(self, user, twitter_profile):
        """Test bookmark_detail returns 404 for non-existent tweet."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/bookmarks/bookmark/nonexistent/')
        
        assert response.status_code == 404
    
    def test_bookmark_detail_success(self, user, twitter_profile, tweet):
        """Test bookmark_detail displays bookmark."""
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/bookmark/{tweet.tweet_id}/')
        
        assert response.status_code == 200
        assert response.context['bookmark'] == tweet
    
    def test_bookmark_detail_wrong_user(self, user, twitter_profile, tweet):
        """Test bookmark_detail denies access to other user's bookmarks."""
        # Create another user
        other_user = User.objects.create_user(username='other', email='other@example.com')
        other_profile = TwitterProfile.objects.create(
            user=other_user,
            twitter_username='otheruser',
            twitter_user_id='999'
        )
        other_profile.set_credentials('otheruser', password='pass')
        
        client = Client()
        client.force_login(other_user)
        
        response = client.get(f'/bookmark/{tweet.tweet_id}/')
        
        assert response.status_code == 404  # Should not find tweet for other user


@pytest.mark.django_db
class TestDeleteBookmark:
    """Tests for delete_bookmark view."""
    
    def test_delete_bookmark_requires_authentication(self, tweet):
        """Test delete_bookmark requires login."""
        client = Client()
        
        response = client.post(f'/bookmark/{tweet.tweet_id}/delete/')
        
        assert response.status_code == 302
    
    def test_delete_bookmark_success(self, user, twitter_profile, tweet):
        """Test delete_bookmark deletes bookmark."""
        client = Client()
        client.force_login(user)
        
        tweet_id = tweet.tweet_id
        response = client.post(f'/bookmark/{tweet_id}/delete/')
        
        assert response.status_code == 302  # Redirect after delete
        assert not Tweet.objects.filter(tweet_id=tweet_id, is_bookmark=True).exists()
    
    def test_delete_bookmark_wrong_user(self, user, twitter_profile, tweet):
        """Test delete_bookmark denies access to other user's bookmarks."""
        other_user = User.objects.create_user(username='other', email='other@example.com')
        
        client = Client()
        client.force_login(other_user)
        
        response = client.post(f'/bookmark/{tweet.tweet_id}/delete/')
        
        assert response.status_code == 404
        assert Tweet.objects.filter(tweet_id=tweet.tweet_id).exists()  # Still exists


@pytest.mark.django_db
class TestDeleteAllBookmarks:
    """Tests for delete_all_bookmarks view."""
    
    def test_delete_all_bookmarks_requires_authentication(self):
        """Test delete_all_bookmarks requires login."""
        client = Client()
        
        response = client.post('/delete-all/')
        
        assert response.status_code == 302
    
    def test_delete_all_bookmarks_success(self, user, twitter_profile):
        """Test delete_all_bookmarks deletes all user's bookmarks."""
        from django.utils import timezone
        # Create multiple bookmarks
        for i in range(5):
            Tweet.objects.create(
                tweet_id=f'123{i}',
                twitter_profile=twitter_profile,
                author_username='testauthor',
                text_content=f'Tweet {i}',
                created_at=timezone.now(),
                is_bookmark=True
            )
        
        client = Client()
        client.force_login(user)
        
        response = client.post('/delete-all/')
        
        assert response.status_code == 302
        assert Tweet.objects.filter(twitter_profile=twitter_profile, is_bookmark=True).count() == 0


@pytest.mark.django_db
class TestDownloadPDF:
    """Tests for download_pdf view."""
    
    def test_download_pdf_requires_authentication(self, tweet):
        """Test download_pdf requires login."""
        client = Client()
        
        response = client.get(f'/bookmark/{tweet.tweet_id}/pdf/')
        
        assert response.status_code == 302
    
    @patch('bookmarks_app.views.PDFGenerator')
    def test_download_pdf_success(self, mock_pdf_generator, user, twitter_profile, tweet):
        """Test download_pdf generates and returns PDF."""
        mock_generator = MagicMock()
        mock_generator.generate_pdf.return_value = b'fake pdf content'
        mock_pdf_generator.return_value = mock_generator
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/bookmark/{tweet.tweet_id}/pdf/')
        
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/pdf'
        assert 'attachment' in response['Content-Disposition']
        assert mock_generator.generate_pdf.called
    
    def test_download_pdf_not_found(self, user, twitter_profile):
        """Test download_pdf returns 404 for non-existent tweet."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/bookmark/nonexistent/pdf/')
        
        assert response.status_code == 404


@pytest.mark.django_db
class TestCuratedFeed:
    """Tests for curated_feed view."""
    
    def test_curated_feed_requires_authentication(self):
        """Test curated_feed requires login."""
        client = Client()
        
        response = client.get('/curated-feed/')
        
        assert response.status_code == 302
    
    def test_curated_feed_no_twitter_profile(self, user):
        """Test curated_feed redirects when no Twitter profile."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/curated-feed/')
        
        assert response.status_code == 302
    
    def test_curated_feed_displays_feeds(self, user, twitter_profile):
        """Test curated_feed displays user's curated feeds."""
        from bookmarks_app.models import CuratedFeed
        
        feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=twitter_profile,
            num_tweets_fetched=10,
            num_categories=3
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/curated-feed/')
        
        assert response.status_code == 200
        assert 'latest_feed' in response.context
        assert response.context['latest_feed'] == feed

