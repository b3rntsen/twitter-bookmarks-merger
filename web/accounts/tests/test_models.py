"""
Tests for accounts models.
"""
import pytest
from django.contrib.auth.models import User
from accounts.models import UserProfile


@pytest.mark.django_db
class TestUserProfile:
    """Tests for UserProfile model."""
    
    def test_user_profile_creation(self, user):
        """Test UserProfile can be created with valid data."""
        profile = UserProfile.objects.create(
            user=user,
            ai_provider='anthropic'
        )
        
        assert profile.user == user
        assert profile.ai_provider == 'anthropic'
        assert profile.created_at is not None
        assert profile.updated_at is not None
    
    def test_user_profile_default_ai_provider(self, user):
        """Test UserProfile defaults to 'anthropic'."""
        profile = UserProfile.objects.create(
            user=user
        )
        
        assert profile.ai_provider == 'anthropic'
    
    def test_user_profile_one_to_one_relationship(self, user):
        """Test UserProfile has one-to-one relationship with User."""
        profile1 = UserProfile.objects.create(
            user=user,
            ai_provider='anthropic'
        )
        
        # Creating another profile for same user should fail
        with pytest.raises(Exception):  # IntegrityError
            UserProfile.objects.create(
                user=user,
                ai_provider='openai'
            )
    
    def test_user_profile_str_representation(self, user):
        """Test UserProfile string representation."""
        profile = UserProfile.objects.create(
            user=user,
            ai_provider='anthropic'
        )
        
        assert user.email in str(profile)
        assert 'Profile' in str(profile)
    
    def test_user_profile_ai_provider_choices(self, user):
        """Test UserProfile AI provider choices."""
        # Valid choice
        profile1 = UserProfile.objects.create(
            user=user,
            ai_provider='anthropic'
        )
        assert profile1.ai_provider == 'anthropic'
        
        # Another valid choice
        user2 = User.objects.create_user(username='user2', email='user2@example.com')
        profile2 = UserProfile.objects.create(
            user=user2,
            ai_provider='openai'
        )
        assert profile2.ai_provider == 'openai'

