"""
Tests for ListsService.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from lists_app.services import ListsService, retry_with_exponential_backoff
from lists_app.models import TwitterList, ListTweet
from twitter.models import TwitterProfile, Tweet


@pytest.mark.django_db
class TestRetryWithExponentialBackoff:
    """Tests for retry_with_exponential_backoff utility."""
    
    def test_retry_succeeds_on_first_attempt(self):
        """Test retry succeeds immediately."""
        func = Mock(return_value='success')
        
        result = retry_with_exponential_backoff(func)
        
        assert result == 'success'
        assert func.call_count == 1
    
    def test_retry_succeeds_after_retries(self):
        """Test retry succeeds after some failures."""
        func = Mock(side_effect=[Exception('Error'), Exception('Error'), 'success'])
        
        with patch('lists_app.services.time.sleep'):
            result = retry_with_exponential_backoff(func, max_retries=3)
        
        assert result == 'success'
        assert func.call_count == 3
    
    def test_retry_fails_after_max_retries(self):
        """Test retry raises exception after max retries."""
        func = Mock(side_effect=Exception('Error'))
        
        with patch('lists_app.services.time.sleep'):
            with pytest.raises(Exception):
                retry_with_exponential_backoff(func, max_retries=2)
        
        assert func.call_count == 3  # Initial + 2 retries
    
    def test_retry_handles_rate_limit(self):
        """Test retry handles rate limit errors."""
        func = Mock(side_effect=[Exception('429 Rate Limit'), 'success'])
        
        with patch('lists_app.services.time.sleep'):
            result = retry_with_exponential_backoff(func, max_retries=1)
        
        assert result == 'success'


@pytest.mark.django_db
class TestListsService:
    """Tests for ListsService class."""
    
    def test_lists_service_initialization(self, twitter_profile):
        """Test ListsService can be initialized."""
        with patch('lists_app.services.TwitterScraper') as mock_scraper_class:
            mock_scraper = MagicMock()
            mock_scraper_class.return_value = mock_scraper
            
            # Mock credentials
            twitter_profile.set_credentials('testuser', password='testpass')
            
            service = ListsService(twitter_profile, use_playwright=False)
            
            assert service.twitter_profile == twitter_profile
            assert service.scraper is not None
            assert service.use_playwright is False
    
    def test_lists_service_initialization_no_credentials(self, twitter_profile):
        """Test ListsService raises error when credentials unavailable."""
        twitter_profile.encrypted_credentials = ''
        
        with pytest.raises(ValueError, match='credentials not available'):
            ListsService(twitter_profile)
    
    @patch('lists_app.services.retry_with_exponential_backoff')
    def test_get_user_lists_success(self, mock_retry, twitter_profile):
        """Test get_user_lists successfully fetches lists."""
        # Setup mocks
        mock_scraper = MagicMock()
        mock_scraper.driver = MagicMock()
        mock_scraper.login.return_value = True
        
        with patch('lists_app.services.TwitterScraper', return_value=mock_scraper):
            twitter_profile.set_credentials('testuser', password='testpass')
            service = ListsService(twitter_profile, use_playwright=False)
            service.scraper = mock_scraper
            
            # Mock browser interactions
            mock_element = MagicMock()
            mock_element.get_attribute.return_value = 'https://x.com/i/lists/123456'
            mock_element.text = 'Test List'
            
            service._find_elements = Mock(return_value=[mock_element])
            service._get_text = Mock(return_value='Test List')
            service._get_current_url = Mock(return_value='https://x.com/testuser/lists')
            service._navigate_to = Mock()
            service._click = Mock()
            service._find_list_cells = Mock(return_value=[mock_element])
            service._extract_list_names = Mock(return_value=[{'list_id': '123456', 'list_name': 'Test List', 'list_url': 'https://x.com/i/lists/123456', 'list_slug': 'test-list'}])
            service._process_lists = Mock(return_value=[{'list_id': '123456', 'list_name': 'Test List', 'list_url': 'https://x.com/i/lists/123456', 'list_slug': 'test-list'}])
            
            # Mock retry to just execute the function
            def execute_func(func, max_retries=None, initial_wait=None, max_wait=None, backoff_factor=None):
                return func()
            mock_retry.side_effect = execute_func
            
            lists = service.get_user_lists()
            
            # Should return list of dictionaries
            assert isinstance(lists, list)
    
    def test_lists_service_close(self, twitter_profile):
        """Test ListsService.close cleans up scraper."""
        mock_scraper = MagicMock()
        
        with patch('lists_app.services.TwitterScraper', return_value=mock_scraper):
            twitter_profile.set_credentials('testuser', password='testpass')
            service = ListsService(twitter_profile)
            service.scraper = mock_scraper
            
            service.close()
            
            assert service.scraper is None
            mock_scraper.close.assert_called_once()
    
    def test_lists_service_context_manager(self, twitter_profile):
        """Test ListsService works as context manager."""
        mock_scraper = MagicMock()
        
        with patch('lists_app.services.TwitterScraper', return_value=mock_scraper):
            twitter_profile.set_credentials('testuser', password='testpass')
            
            with ListsService(twitter_profile) as service:
                assert service is not None
            
            # Should be closed after context
            mock_scraper.close.assert_called_once()
