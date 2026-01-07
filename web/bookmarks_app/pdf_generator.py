"""
PDF generator for Twitter bookmarks.
"""
import logging
from django.template.loader import render_to_string
from django.conf import settings
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
from twitter.models import Tweet
from io import BytesIO
import os

logger = logging.getLogger(__name__)


class PDFGenerator:
    """Generate PDFs from bookmarks."""
    
    def __init__(self):
        self.font_config = FontConfiguration()
    
    def generate_pdf(self, bookmark: Tweet, thread_tweets: list = None) -> bytes:
        """Generate PDF for a bookmark and its thread."""
        # Get tweet URL from raw_data, ensure it's a full URL
        tweet_url = None
        if bookmark.raw_data and 'url' in bookmark.raw_data:
            url = bookmark.raw_data['url']
            if url:
                if not url.startswith('http'):
                    # Relative URL, make it absolute
                    tweet_url = f"https://x.com{url}" if url.startswith('/') else f"https://x.com/{url}"
                else:
                    tweet_url = url
        
        # Prepare context
        context = {
            'bookmark': bookmark,
            'thread_tweets': thread_tweets or [],
            'media': bookmark.media.all(),
            'MEDIA_URL': settings.MEDIA_URL,
            'MEDIA_ROOT': settings.MEDIA_ROOT,
            'tweet_url': tweet_url,
        }
        
        # Render HTML template
        html_string = render_to_string('bookmarks/pdf_template.html', context)
        
        # Generate PDF
        # Use absolute path for base_url to resolve media files
        base_url = str(settings.MEDIA_ROOT.absolute()) if hasattr(settings.MEDIA_ROOT, 'absolute') else str(settings.MEDIA_ROOT)
        html = HTML(string=html_string, base_url=base_url)
        css = CSS(string=self._get_pdf_css())
        
        pdf_file = BytesIO()
        html.write_pdf(pdf_file, stylesheets=[css], font_config=self.font_config)
        pdf_file.seek(0)
        
        return pdf_file.read()
    
    def _get_pdf_css(self) -> str:
        """Get CSS styles for PDF."""
        return """
            @page {
                size: A4;
                margin: 2cm;
            }
            
            body {
                font-family: Arial, sans-serif;
                font-size: 12pt;
                line-height: 1.6;
                color: #333;
            }
            
            .bookmark-header {
                border-bottom: 2px solid #1DA1F2;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }
            
            .author-name {
                font-size: 16pt;
                font-weight: bold;
                color: #1DA1F2;
            }
            
            .bookmark-date {
                font-size: 10pt;
                color: #666;
                margin-top: 5px;
            }
            
            .bookmark-content {
                margin: 20px 0;
                padding: 15px;
                background-color: #f9f9f9;
                border-left: 4px solid #1DA1F2;
            }
            
            .bookmark-metrics {
                margin: 15px 0;
                font-size: 10pt;
                color: #666;
            }
            
            .bookmark-metrics span {
                margin-right: 15px;
            }
            
            .media-section {
                margin: 20px 0;
                page-break-inside: avoid;
            }
            
            .media-item {
                margin: 10px 0;
                text-align: center;
            }
            
            .media-item img {
                max-width: 100%;
                height: auto;
                border: 1px solid #ddd;
            }
            
            .thread-section {
                margin-top: 30px;
                border-top: 1px solid #ddd;
                padding-top: 20px;
            }
            
            .thread-tweet {
                margin: 15px 0;
                padding: 10px;
                background-color: #f5f5f5;
                border-left: 2px solid #ccc;
            }
            
            .thread-header {
                font-size: 10pt;
                color: #666;
                margin-bottom: 5px;
            }
            
            .thread-content {
                font-size: 11pt;
            }
            
            .video-thumbnail {
                max-width: 300px;
                border: 1px solid #ddd;
            }
            
            .video-link {
                display: block;
                margin-top: 5px;
                color: #1DA1F2;
                text-decoration: none;
            }
            
            .tweet-link {
                margin: 10px 0;
                font-size: 10pt;
            }
            
            .tweet-link a {
                color: #1DA1F2;
                text-decoration: none;
            }
            
            .tweet-link a:hover {
                text-decoration: underline;
            }
            
            .media-link {
                margin-top: 5px;
                font-size: 9pt;
            }
            
            .media-link a {
                color: #1DA1F2;
                text-decoration: none;
            }
            
            .media-item a {
                display: inline-block;
            }
            
            .media-item a img {
                border: 1px solid #1DA1F2;
            }
        """

