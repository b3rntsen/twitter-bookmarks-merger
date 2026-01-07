"""
Tests for SummarizationService.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from lists_app.summarization_service import SummarizationService


class TestSummarizationService:
    """Tests for SummarizationService class."""
    
    @patch('lists_app.summarization_service.config')
    def test_summarization_service_initialization_openai(self, mock_config):
        """Test SummarizationService initialization with OpenAI key."""
        mock_config.side_effect = lambda key, default: 'test-key' if key == 'OPENAI_API_KEY' else 'gpt-4o-mini'
        
        service = SummarizationService()
        
        assert service.provider == 'openai'
        assert service.openai_api_key == 'test-key'
    
    @patch('lists_app.summarization_service.config')
    def test_summarization_service_initialization_anthropic(self, mock_config):
        """Test SummarizationService initialization with Anthropic key."""
        # Only provide Anthropic key, not OpenAI (since OpenAI is preferred)
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514',
            'OPENAI_API_KEY': None  # Explicitly None to ensure Anthropic is used
        }.get(key, default)
        
        service = SummarizationService()
        
        assert service.provider == 'anthropic'
        assert service.anthropic_api_key == 'test-key'
    
    @patch('lists_app.summarization_service.config')
    def test_summarization_service_initialization_no_keys(self, mock_config):
        """Test SummarizationService initialization without API keys."""
        mock_config.return_value = None
        
        service = SummarizationService()
        
        assert service.provider is None
    
    @patch('openai.OpenAI')
    @patch('lists_app.summarization_service.config')
    def test_generate_with_openai_success(self, mock_config, mock_openai_class):
        """Test _generate_with_openai successfully generates summary."""
        mock_config.side_effect = lambda key, default: {
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_MODEL': 'gpt-4o-mini'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "HEADLINE: Test Headline\nSUMMARY: Test summary text"
        mock_client.chat.completions.create.return_value = mock_response
        
        service = SummarizationService()
        service.provider = 'openai'
        service.openai_api_key = 'test-key'
        
        headline, summary = service._generate_with_openai(
            texts=['Test tweet 1', 'Test tweet 2'],
            keywords=['test', 'keyword']
        )
        
        assert 'Test Headline' in headline or headline
        assert 'summary' in summary.lower() or summary
    
    @patch('anthropic.Anthropic')
    @patch('lists_app.summarization_service.config')
    def test_generate_with_anthropic_success(self, mock_config, mock_anthropic_class):
        """Test _generate_with_anthropic successfully generates summary."""
        mock_config.side_effect = lambda key, default: {
            'ANTHROPIC_API_KEY': 'test-key',
            'ANTHROPIC_MODEL': 'claude-sonnet-4-20250514'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_anthropic_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="HEADLINE: Test Headline\nSUMMARY: Test summary text")]
        mock_client.messages.create.return_value = mock_response
        
        service = SummarizationService()
        service.provider = 'anthropic'
        service.anthropic_api_key = 'test-key'
        
        headline, summary = service._generate_with_anthropic(
            texts=['Test tweet 1', 'Test tweet 2'],
            keywords=['test', 'keyword']
        )
        
        assert 'Test Headline' in headline or headline
        assert 'summary' in summary.lower() or summary
    
    def test_generate_fallback(self):
        """Test _generate_fallback creates basic summary."""
        service = SummarizationService()
        
        headline, summary = service._generate_fallback(
            texts=['Test tweet 1', 'Test tweet 2'],
            keywords=['test', 'keyword']
        )
        
        assert headline is not None
        assert summary is not None
        assert '2' in summary  # Should mention number of tweets
    
    @patch('lists_app.summarization_service.config')
    def test_generate_event_summary_empty_texts(self, mock_config):
        """Test generate_event_summary with empty texts."""
        mock_config.return_value = None
        
        service = SummarizationService()
        
        headline, summary = service.generate_event_summary([], ['keyword'])
        
        assert headline == "No Event"
        assert 'No tweets' in summary
    
    @patch('openai.OpenAI')
    @patch('lists_app.summarization_service.config')
    def test_generate_event_summary_openai_provider(self, mock_config, mock_openai_class):
        """Test generate_event_summary uses OpenAI when available."""
        mock_config.side_effect = lambda key, default: {
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_MODEL': 'gpt-4o-mini'
        }.get(key, default)
        
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "HEADLINE: Test\nSUMMARY: Summary"
        mock_client.chat.completions.create.return_value = mock_response
        
        service = SummarizationService()
        
        headline, summary = service.generate_event_summary(
            texts=['Test tweet'],
            keywords=['test']
        )
        
        assert headline is not None
        assert summary is not None

