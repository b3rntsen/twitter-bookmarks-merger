"""
Tests for PDFGenerator.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
from twitter.models import Tweet, TwitterProfile
from bookmarks_app.pdf_generator import PDFGenerator


@pytest.mark.django_db
class TestPDFGenerator:
    """Tests for PDFGenerator class."""
    
    def test_pdf_generator_initialization(self):
        """Test PDFGenerator can be initialized."""
        generator = PDFGenerator()
        
        assert generator.font_config is not None
    
    @patch('bookmarks_app.pdf_generator.render_to_string')
    @patch('bookmarks_app.pdf_generator.HTML')
    @patch('bookmarks_app.pdf_generator.CSS')
    def test_generate_pdf_success(self, mock_css, mock_html_class, mock_render, twitter_profile, tweet):
        """Test generate_pdf successfully generates PDF."""
        # Setup mocks
        mock_render.return_value = '<html>Test PDF</html>'
        mock_html = MagicMock()
        mock_pdf_file = BytesIO(b'fake pdf content')
        mock_html.write_pdf.return_value = None
        mock_html_class.return_value = mock_html
        
        generator = PDFGenerator()
        
        pdf_bytes = generator.generate_pdf(tweet)
        
        assert mock_render.called
        assert mock_html_class.called
        assert mock_html.write_pdf.called
    
    @patch('bookmarks_app.pdf_generator.render_to_string')
    @patch('bookmarks_app.pdf_generator.HTML')
    def test_generate_pdf_with_thread(self, mock_html_class, mock_render, twitter_profile, tweet):
        """Test generate_pdf includes thread tweets."""
        mock_render.return_value = '<html>Test PDF</html>'
        mock_html = MagicMock()
        mock_html.write_pdf.return_value = None
        mock_html_class.return_value = mock_html
        
        # Create thread tweet
        thread_tweet = Tweet.objects.create(
            tweet_id='222',
            twitter_profile=twitter_profile,
            author_username='testauthor',
            text_content='Thread reply',
            created_at=tweet.created_at
        )
        
        generator = PDFGenerator()
        
        pdf_bytes = generator.generate_pdf(tweet, thread_tweets=[thread_tweet])
        
        # Verify thread tweets were passed to template
        call_args = mock_render.call_args
        # render_to_string(template_name, context=None, ...)
        # context is second positional arg
        context = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('context', {})
        assert 'thread_tweets' in context
        assert len(context['thread_tweets']) == 1
    
    @patch('bookmarks_app.pdf_generator.render_to_string')
    @patch('bookmarks_app.pdf_generator.HTML')
    def test_generate_pdf_with_media(self, mock_html_class, mock_render, twitter_profile, tweet):
        """Test generate_pdf includes media."""
        from twitter.models import TweetMedia
        
        # Add media to tweet
        TweetMedia.objects.create(
            tweet=tweet,
            media_type='image',
            file_path='/media/image.png',
            original_url='https://example.com/image.png'
        )
        
        mock_render.return_value = '<html>Test PDF</html>'
        mock_html = MagicMock()
        mock_html.write_pdf.return_value = None
        mock_html_class.return_value = mock_html
        
        generator = PDFGenerator()
        
        pdf_bytes = generator.generate_pdf(tweet)
        
        # Verify media was passed to template
        call_args = mock_render.call_args
        # render_to_string(template_name, context=None, ...)
        # context is second positional arg
        context = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get('context', {})
        assert 'media' in context
        assert context['media'].count() == 1
    
    def test_get_pdf_css_returns_string(self):
        """Test _get_pdf_css returns CSS string."""
        generator = PDFGenerator()
        
        css = generator._get_pdf_css()
        
        assert isinstance(css, str)
        assert '@page' in css
        assert 'body' in css
        assert 'font-family' in css

