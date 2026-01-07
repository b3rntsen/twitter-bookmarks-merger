"""
Tests for accounts views.
"""
import pytest
from django.test import Client
from accounts.models import UserProfile


@pytest.mark.django_db
class TestProfile:
    """Tests for profile view."""
    
    def test_profile_requires_authentication(self):
        """Test profile requires login."""
        client = Client()
        
        response = client.get('/accounts/profile/')
        
        assert response.status_code == 302
    
    def test_profile_displays_user_info(self, user):
        """Test profile displays user information."""
        client = Client()
        client.force_login(user)
        
        response = client.get('/accounts/profile/')
        
        assert response.status_code == 200
        assert 'user' in response.context or 'profile' in response.context
    
    def test_profile_displays_userprofile(self, user):
        """Test profile displays UserProfile if exists."""
        UserProfile.objects.create(
            user=user,
            ai_provider='anthropic'
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get('/accounts/profile/')
        
        assert response.status_code == 200

