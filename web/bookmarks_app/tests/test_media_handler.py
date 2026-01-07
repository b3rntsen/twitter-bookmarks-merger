"""
Tests for MediaDownloader.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, mock_open
import os
from bookmarks_app.media_handler import MediaDownloader


class TestMediaDownloader:
    """Tests for MediaDownloader class."""
    
    def test_media_downloader_initialization(self, settings):
        """Test MediaDownloader can be initialized."""
        with patch('bookmarks_app.media_handler.os.makedirs'):
            downloader = MediaDownloader()
            
            assert downloader.media_root is not None
            assert downloader.tweets_dir is not None
    
    @patch('bookmarks_app.media_handler.requests.get')
    @patch('bookmarks_app.media_handler.os.makedirs')
    @patch('bookmarks_app.media_handler.os.listdir')
    @patch('builtins.open', new_callable=mock_open, read_data=b'fake image data')
    def test_download_media_success(self, mock_file, mock_listdir, mock_makedirs, mock_get, settings):
        """Test download_media successfully downloads media."""
        # Setup mocks
        mock_listdir.return_value = []
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b'chunk1', b'chunk2']
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        downloader = MediaDownloader()
        
        file_path, thumbnail_path = downloader.download_media(
            media_url='https://example.com/image.jpg',
            tweet_id='1234567890',
            media_type='image'
        )
        
        assert file_path is not None
        assert mock_get.called
        assert mock_file.called
    
    @patch('bookmarks_app.media_handler.requests.get')
    @patch('bookmarks_app.media_handler.os.makedirs')
    def test_download_media_request_error(self, mock_makedirs, mock_get, settings):
        """Test download_media handles request errors gracefully."""
        mock_get.side_effect = Exception('Network error')
        
        downloader = MediaDownloader()
        
        file_path, thumbnail_path = downloader.download_media(
            media_url='https://example.com/image.jpg',
            tweet_id='1234567890',
            media_type='image'
        )
        
        assert file_path is None
        assert thumbnail_path is None
    
    def test_get_file_extension_from_url(self, settings):
        """Test _get_file_extension extracts extension from URL."""
        with patch('bookmarks_app.media_handler.os.makedirs'):
            downloader = MediaDownloader()
            
            ext = downloader._get_file_extension('https://example.com/image.jpg?size=large', 'image')
            assert ext == '.jpg'
    
    def test_get_file_extension_default(self, settings):
        """Test _get_file_extension returns default extension."""
        with patch('bookmarks_app.media_handler.os.makedirs'):
            downloader = MediaDownloader()
            
            ext = downloader._get_file_extension('https://example.com/image', 'image')
            assert ext == '.jpg'
            
            ext = downloader._get_file_extension('https://example.com/video', 'video')
            assert ext == '.mp4'
    
    @patch('bookmarks_app.media_handler.subprocess.run')
    @patch('bookmarks_app.media_handler.os.path.exists')
    @patch('bookmarks_app.media_handler.os.makedirs')
    def test_generate_video_thumbnail_success(self, mock_makedirs, mock_exists, mock_subprocess, settings):
        """Test _generate_video_thumbnail successfully generates thumbnail."""
        mock_exists.return_value = True
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        downloader = MediaDownloader()
        
        thumbnail_path = downloader._generate_video_thumbnail(
            video_path='/media/video.mp4',
            output_dir='/media/tweets/123'
        )
        
        assert thumbnail_path is not None
        assert mock_subprocess.called
    
    @patch('bookmarks_app.media_handler.subprocess.run')
    @patch('bookmarks_app.media_handler.os.makedirs')
    def test_generate_video_thumbnail_ffmpeg_not_found(self, mock_makedirs, mock_subprocess, settings):
        """Test _generate_video_thumbnail creates placeholder when ffmpeg not found."""
        mock_subprocess.side_effect = FileNotFoundError()
        
        with patch('bookmarks_app.media_handler.Image') as mock_image:
            mock_img = MagicMock()
            mock_image.new.return_value = mock_img
            
            downloader = MediaDownloader()
            
            thumbnail_path = downloader._generate_video_thumbnail(
                video_path='/media/video.mp4',
                output_dir='/media/tweets/123'
            )
            
            assert thumbnail_path is not None
            assert mock_image.new.called
    
    @patch('bookmarks_app.media_handler.os.path.getsize')
    @patch('bookmarks_app.media_handler.os.makedirs')
    def test_get_file_size_success(self, mock_makedirs, mock_getsize, settings):
        """Test get_file_size returns file size."""
        mock_getsize.return_value = 1024
        
        downloader = MediaDownloader()
        
        size = downloader.get_file_size('tweets/123/image.jpg')
        
        assert size == 1024
    
    @patch('bookmarks_app.media_handler.os.path.getsize')
    @patch('bookmarks_app.media_handler.os.makedirs')
    def test_get_file_size_error(self, mock_makedirs, mock_getsize, settings):
        """Test get_file_size returns 0 on error."""
        mock_getsize.side_effect = OSError('File not found')
        
        downloader = MediaDownloader()
        
        size = downloader.get_file_size('tweets/123/image.jpg')
        
        assert size == 0

