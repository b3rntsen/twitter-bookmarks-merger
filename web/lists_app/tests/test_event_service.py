"""
Tests for EventService.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date
from lists_app.event_service import EventService
from lists_app.models import TwitterList, ListTweet, Event, EventTweet
from twitter.models import Tweet, TwitterProfile


@pytest.mark.django_db
class TestEventService:
    """Tests for EventService class."""
    
    def test_event_service_initialization(self):
        """Test EventService can be initialized."""
        service = EventService(min_tweets_per_event=3, similarity_threshold=0.3)
        
        assert service.min_tweets_per_event == 3
        assert service.similarity_threshold == 0.3
        assert service.summarization_service is not None
    
    def test_preprocess_text_removes_urls(self):
        """Test _preprocess_text removes URLs."""
        service = EventService()
        
        text = service._preprocess_text("Check this out: https://example.com/article")
        
        assert 'https://example.com' not in text
        assert 'check this out' in text.lower()
    
    def test_preprocess_text_removes_mentions(self):
        """Test _preprocess_text removes @mentions."""
        service = EventService()
        
        text = service._preprocess_text("@user1 and @user2 discussed this")
        
        assert '@user1' not in text
        assert '@user2' not in text
        assert 'discussed' in text.lower()
    
    def test_preprocess_text_handles_hashtags(self):
        """Test _preprocess_text handles hashtags."""
        service = EventService()
        
        text = service._preprocess_text("#AI and #MachineLearning are trending")
        
        assert '#AI' not in text
        assert '#MachineLearning' not in text
        assert 'ai' in text.lower()
        assert 'machinelearning' in text.lower()
    
    def test_preprocess_text_empty_string(self):
        """Test _preprocess_text handles empty string."""
        service = EventService()
        
        text = service._preprocess_text("")
        
        assert text == ""
    
    def test_extract_keywords_empty_list(self):
        """Test _extract_keywords with empty list."""
        service = EventService()
        
        keywords = service._extract_keywords([])
        
        assert keywords == []
    
    def test_extract_keywords_extracts_keywords(self):
        """Test _extract_keywords extracts top keywords."""
        service = EventService()
        
        texts = [
            "AI is transforming technology",
            "Machine learning and AI are the future",
            "Artificial intelligence will change everything"
        ]
        
        keywords = service._extract_keywords(texts, top_n=10)
        
        assert len(keywords) > 0
        # Check that we get some keywords (may vary based on stop word filtering)
        keywords_lower = [kw.lower() for kw in keywords]
        # Should contain some relevant words
        relevant_words = ['ai', 'artificial', 'intelligence', 'machine', 'learning', 'technology', 'transforming', 'future', 'change', 'everything']
        assert any(word in ' '.join(keywords_lower) for word in relevant_words)
    
    def test_extract_keywords_removes_stop_words(self):
        """Test _extract_keywords removes common stop words."""
        service = EventService()
        
        texts = ["The and for are but not you all can"]
        
        keywords = service._extract_keywords(texts, top_n=10)
        
        # Should not contain common stop words
        stop_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can'}
        assert not any(kw.lower() in stop_words for kw in keywords)
    
    @patch('sklearn.metrics.pairwise.cosine_similarity')
    @patch('sklearn.feature_extraction.text.TfidfVectorizer')
    def test_calculate_similarity_matrix_with_sklearn(self, mock_tfidf, mock_cosine):
        """Test _calculate_similarity_matrix uses sklearn when available."""
        service = EventService()
        
        # Mock sklearn components
        mock_vectorizer = MagicMock()
        mock_tfidf.return_value = mock_vectorizer
        mock_matrix = MagicMock()
        mock_vectorizer.fit_transform.return_value = mock_matrix
        mock_cosine.return_value = [[1.0, 0.5], [0.5, 1.0]]
        
        texts = ["AI is great", "Machine learning is awesome"]
        matrix = service._calculate_similarity_matrix(texts)
        
        assert mock_tfidf.called
        assert mock_cosine.called
    
    def test_calculate_similarity_matrix_fallback(self):
        """Test _calculate_similarity_matrix uses fallback when sklearn unavailable."""
        service = EventService()
        
        # Mock the import to raise ImportError when trying to import sklearn
        original_import = __import__
        def mock_import(name, *args, **kwargs):
            if 'sklearn' in name:
                raise ImportError('sklearn not available')
            return original_import(name, *args, **kwargs)
        
        with patch('builtins.__import__', side_effect=mock_import):
            texts = ["AI is great", "Machine learning is awesome"]
            matrix = service._calculate_similarity_matrix(texts)
            
            # Should return a matrix (even if simple fallback)
            assert matrix is not None
            assert len(matrix) == len(texts)
            # Fallback creates identity-like matrix
            assert matrix[0][0] == 1.0  # Diagonal should be 1.0

