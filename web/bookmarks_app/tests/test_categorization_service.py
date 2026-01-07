"""
Tests for TweetCategorizationService.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from bookmarks_app.categorization_service import TweetCategorizationService


class TestTweetCategorizationService:
    """Tests for TweetCategorizationService class."""
    
    @patch('anthropic.Anthropic')
    def test_categorization_service_initialization_anthropic(self, mock_anthropic_class):
        """Test TweetCategorizationService initialization with anthropic provider."""
        with patch('bookmarks_app.categorization_service.config') as mock_config:
            mock_config.side_effect = lambda key, default: {
                'ANTHROPIC_API_KEY': 'test-key',
                'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
            }.get(key, default)
            
            mock_client = MagicMock()
            mock_anthropic_class.return_value = mock_client
            
            service = TweetCategorizationService(provider='anthropic')
            service._initialize()
            
            assert service.provider == 'anthropic'
            assert service._initialized is True
    
    @patch('openai.OpenAI')
    def test_categorization_service_initialization_openai(self, mock_openai_class):
        """Test TweetCategorizationService initialization with openai provider."""
        with patch('bookmarks_app.categorization_service.config') as mock_config:
            mock_config.side_effect = lambda key, default: {
                'OPENAI_API_KEY': 'test-key',
                'OPENAI_MODEL': 'gpt-4o'
            }.get(key, default)
            
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            
            service = TweetCategorizationService(provider='openai')
            service._initialize()
            
            assert service.provider == 'openai'
            assert service._initialized is True
    
    def test_categorization_service_invalid_provider(self):
        """Test TweetCategorizationService raises error for invalid provider."""
        service = TweetCategorizationService(provider='invalid')
        
        with pytest.raises(ValueError, match='Unknown provider'):
            service._initialize()
    
    def test_categorize_tweets_empty_list(self):
        """Test categorize_tweets with empty list returns empty dict."""
        service = TweetCategorizationService()
        
        result = service.categorize_tweets([])
        
        assert result == {}
    
    @patch('anthropic.Anthropic')
    @patch('bookmarks_app.categorization_service.config')
    def test_categorize_tweets_success(self, mock_config, mock_anthropic_class):
        """Test categorize_tweets successfully categorizes tweets."""
        # Setup mocks
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        
        # Mock AI response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"categories": {"Technology": {"description": "Tech tweets", "tweet_indices": [0]}}}')]
        mock_client.messages.create.return_value = mock_response
        
        service = TweetCategorizationService(provider='anthropic')
        
        tweets = [{
            'tweet_id': '123',
            'text_content': 'AI is the future',
            'author_username': 'techuser'
        }]
        
        result = service.categorize_tweets(tweets)
        
        assert 'Technology' in result
        assert len(result['Technology']['tweets']) == 1
    
    @patch('anthropic.Anthropic')
    @patch('bookmarks_app.categorization_service.config')
    def test_categorize_tweets_json_error_fallback(self, mock_config, mock_anthropic_class):
        """Test categorize_tweets falls back to uncategorized on JSON error."""
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        
        # Mock invalid JSON response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='Invalid JSON response')]
        mock_client.messages.create.return_value = mock_response
        
        service = TweetCategorizationService(provider='anthropic')
        
        tweets = [{
            'tweet_id': '123',
            'text_content': 'Test tweet',
            'author_username': 'testuser'
        }]
        
        result = service.categorize_tweets(tweets)
        
        assert 'Uncategorized' in result
        assert len(result['Uncategorized']['tweets']) == 1
    
    @patch('anthropic.Anthropic')
    @patch('bookmarks_app.categorization_service.config')
    def test_summarize_category_success(self, mock_config, mock_anthropic_class):
        """Test summarize_category successfully generates summary."""
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='This is a summary of the tweets.')]
        mock_client.messages.create.return_value = mock_response
        
        service = TweetCategorizationService(provider='anthropic')
        
        tweets = [{
            'tweet_id': '123',
            'text_content': 'Test tweet',
            'author_username': 'testuser',
            'author_display_name': 'Test User'
        }]
        
        summary = service.summarize_category('Technology', tweets)
        
        assert summary == 'This is a summary of the tweets.'
        assert mock_client.messages.create.called
    
    def test_summarize_category_empty_list(self):
        """Test summarize_category with empty list returns message."""
        service = TweetCategorizationService()
        
        summary = service.summarize_category('Technology', [])
        
        assert 'No tweets' in summary or 'Technology' in summary
    
    @patch('anthropic.Anthropic')
    @patch('bookmarks_app.categorization_service.config')
    def test_summarize_category_error_fallback(self, mock_config, mock_anthropic_class):
        """Test summarize_category falls back on error."""
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        mock_client.messages.create.side_effect = Exception('API Error')
        
        service = TweetCategorizationService(provider='anthropic')
        
        tweets = [{
            'tweet_id': '123',
            'text_content': 'Test tweet',
            'author_username': 'testuser',
            'author_display_name': 'Test User'
        }]
        
        summary = service.summarize_category('Technology', tweets)
        
        assert 'tweets' in summary.lower() or 'authors' in summary.lower()

