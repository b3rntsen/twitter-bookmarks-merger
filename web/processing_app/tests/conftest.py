"""
Pytest fixtures for processing_app tests.
"""
import pytest
import logging
import json
import os
from pathlib import Path
from django.contrib.auth.models import User
from twitter.models import TwitterProfile
from lists_app.models import TwitterList


def load_cookies_from_file(file_path='twitter_auth'):
    """
    Load cookies from twitter_auth file.
    Returns cookies in the format expected by TwitterProfile.set_credentials().
    """
    try:
        # Try project root first
        project_root = Path(__file__).parent.parent.parent
        auth_file = project_root / file_path
        if not auth_file.exists():
            # Try current directory
            auth_file = Path(file_path)
        
        if auth_file.exists():
            with open(auth_file, 'r') as f:
                content = f.read().strip()
                # Handle JSON array format
                if content.startswith('['):
                    cookies = json.loads(content)
                else:
                    cookies = json.loads(content)
                    if not isinstance(cookies, list):
                        cookies = [cookies]
                
                # Ensure cookies have required fields for Playwright
                for cookie in cookies:
                    if 'path' not in cookie:
                        cookie['path'] = '/'
                    if 'domain' in cookie and cookie['domain'].startswith('.'):
                        # Keep domain as-is (e.g., '.x.com')
                        pass
                
                logging.info(f"Loaded {len(cookies)} cookies from {auth_file}: {[c.get('name') for c in cookies]}")
                return cookies
        return None
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.warning(f"Could not load cookies from {file_path}: {e}")
        return None


@pytest.fixture
def user(db):
    """
    Get or create a test user.
    First tries to get the first user from database (for real credentials),
    otherwise creates a test user.
    """
    # Try to get first user from database (for real credentials)
    existing_user = User.objects.first()
    if existing_user:
        return existing_user
    
    # Fallback: create test user
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def twitter_profile(db, user):
    """
    Get or create a TwitterProfile with real credentials.
    First tries to get existing profile from database (for real credentials),
    otherwise creates a test profile with cookies from twitter_auth file.
    """
    # Try to get existing profile from database (for real credentials)
    existing_profile = TwitterProfile.objects.filter(user=user).first()
    if existing_profile:
        # Verify it has credentials
        credentials = existing_profile.get_credentials()
        if credentials:
            return existing_profile
    
    # Fallback: create test profile with cookies from twitter_auth
    profile = TwitterProfile.objects.create(
        user=user,
        twitter_username=user.username or 'testuser',
    )
    
    # Load cookies from twitter_auth file
    cookies = load_cookies_from_file('twitter_auth')
    
    # Set credentials with cookies (cookie-based auth to work around bot detection)
    # Use username from user or default, password can be None when using cookies
    username = user.username or user.email or 'testuser'
    profile.set_credentials(username, password=None, cookies=cookies)
    profile.save()
    
    return profile


@pytest.fixture
def twitter_list(db, twitter_profile):
    """
    Get or create a TwitterList for lists-to-tweets tests.
    First tries to get the first list from the profile (for real lists),
    otherwise creates a test list.
    """
    # Try to get existing list from profile (for real lists)
    existing_list = TwitterList.objects.filter(twitter_profile=twitter_profile).first()
    if existing_list:
        return existing_list
    
    # Fallback: create test list
    return TwitterList.objects.create(
        twitter_profile=twitter_profile,
        list_id='test_list_123',
        list_name='Test List',
        member_count=0
    )


# Configure logging to ensure processors' loggers output to console
@pytest.fixture(autouse=True)
def configure_logging():
    """Configure logging for tests to show processor debug output."""
    # Set root logger to INFO level
    logging.root.setLevel(logging.INFO)
    
    # Configure processors' loggers to output at INFO level
    processors_logger = logging.getLogger('processing_app.processors')
    processors_logger.setLevel(logging.INFO)
    
    # Configure tasks logger
    tasks_logger = logging.getLogger('processing_app.tasks')
    tasks_logger.setLevel(logging.INFO)
    
    # Ensure loggers have handlers (pytest will capture these)
    if not processors_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(levelname)s - %(name)s - %(message)s')
        handler.setFormatter(formatter)
        processors_logger.addHandler(handler)
    
    if not tasks_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(levelname)s - %(name)s - %(message)s')
        handler.setFormatter(formatter)
        tasks_logger.addHandler(handler)

