"""
Media downloader for Twitter content.
"""
import os
import requests
import logging
import time
import subprocess
from typing import Optional, Tuple, List
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

# Constants
DEFAULT_REQUEST_TIMEOUT = 30  # seconds
DEFAULT_CHUNK_SIZE = 8192  # bytes
DEFAULT_VIDEO_THUMBNAIL_TIME = '00:00:01'
DEFAULT_THUMBNAIL_QUALITY = '2'
DEFAULT_PLACEHOLDER_SIZE = (320, 180)
MAX_VIDEO_SIZE = 200 * 1024 * 1024  # 200MB in bytes
VIDEO_RETRY_DELAYS = [5, 15, 30]  # seconds - exponential backoff delays
MAX_VIDEO_RETRIES = 3  # Maximum retry attempts


class MediaDownloader:
    """Download and process media files."""
    
    def __init__(self):
        self.media_root = settings.MEDIA_ROOT
        self.tweets_dir = os.path.join(self.media_root, 'tweets')
        os.makedirs(self.tweets_dir, exist_ok=True)
    
    def download_media(
        self,
        media_url: str,
        tweet_id: str,
        media_type: str = 'image'
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Download media file and return file path and thumbnail path.
        
        For videos, implements retry logic for retryable errors and enforces file size limits.
        If media_url is a list, selects highest quality for videos.
        """
        try:
            # Handle list of URLs for video quality selection
            if isinstance(media_url, list) and media_type == 'video':
                media_url = self._select_highest_quality_video(media_url)
            
            # Create tweet directory
            tweet_dir = os.path.join(self.tweets_dir, str(tweet_id))
            os.makedirs(tweet_dir, exist_ok=True)
            
            # Determine file extension
            ext = self._get_file_extension(media_url, media_type)
            
            # Generate filename
            filename = f"{media_type}_{len(os.listdir(tweet_dir)) + 1}{ext}"
            file_path = os.path.join(tweet_dir, filename)
            
            # For videos, implement retry logic for retryable errors
            if media_type == 'video':
                return self._download_video_with_retry(media_url, file_path, tweet_dir, ext)
            
            # For images and other media, use standard download
            return self._download_media_file(media_url, file_path, tweet_dir, media_type)
            
        except Exception as e:
            logger.error(f"Unexpected error downloading media {media_url}: {e}", exc_info=True)
            return None, None
    
    def _download_media_file(
        self,
        media_url: str,
        file_path: str,
        tweet_dir: str,
        media_type: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Download a media file (non-video) and return paths."""
        try:
            # Download file with proper headers (Twitter may require User-Agent)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://x.com/',
            }
            response = requests.get(media_url, stream=True, timeout=DEFAULT_REQUEST_TIMEOUT, headers=headers)
            response.raise_for_status()
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=DEFAULT_CHUNK_SIZE):
                    f.write(chunk)
            
            # Generate thumbnail for videos
            thumbnail_path = None
            if media_type == 'video':
                thumbnail_path = self._generate_video_thumbnail(file_path, tweet_dir)
            
            # Return relative path from media root
            relative_path = os.path.relpath(file_path, self.media_root)
            relative_thumbnail = None
            if thumbnail_path:
                relative_thumbnail = os.path.relpath(thumbnail_path, self.media_root)
            
            return relative_path, relative_thumbnail
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 'unknown'
            logger.warning(f"Could not fetch media {media_url}: HTTP {status_code} - {str(e)}")
            return None, None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not fetch media {media_url}: Network error - {str(e)}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error downloading media {media_url}: {e}", exc_info=True)
            return None, None
    
    def _download_video_with_retry(
        self,
        media_url: str,
        file_path: str,
        tweet_dir: str,
        ext: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Download video with retry logic and file size enforcement."""
        for attempt in range(MAX_VIDEO_RETRIES + 1):
            try:
                # Check file size before downloading (HEAD request)
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://x.com/',
                }
                
                # Check file size first
                head_response = requests.head(media_url, timeout=DEFAULT_REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
                content_length = head_response.headers.get('Content-Length')
                if content_length:
                    file_size = int(content_length)
                    if file_size > MAX_VIDEO_SIZE:
                        logger.warning(f"Video file too large: {file_size} bytes (max: {MAX_VIDEO_SIZE})")
                        return None, None
                
                # Download file
                response = requests.get(media_url, stream=True, timeout=DEFAULT_REQUEST_TIMEOUT, headers=headers)
                response.raise_for_status()
                
                downloaded_size = 0
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=DEFAULT_CHUNK_SIZE):
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        # Check size during download
                        if downloaded_size > MAX_VIDEO_SIZE:
                            logger.warning(f"Video file exceeds size limit during download: {downloaded_size} bytes")
                            os.remove(file_path)  # Clean up partial file
                            return None, None
                
                # Generate thumbnail
                thumbnail_path = self._generate_video_thumbnail(file_path, tweet_dir)
                
                # Return relative paths
                relative_path = os.path.relpath(file_path, self.media_root)
                relative_thumbnail = None
                if thumbnail_path:
                    relative_thumbnail = os.path.relpath(thumbnail_path, self.media_root)
                
                return relative_path, relative_thumbnail
                
            except requests.exceptions.Timeout as e:
                if attempt < MAX_VIDEO_RETRIES and self._should_retry_error(e):
                    delay = VIDEO_RETRY_DELAYS[min(attempt, len(VIDEO_RETRY_DELAYS) - 1)]
                    logger.warning(f"Video download timeout (attempt {attempt + 1}/{MAX_VIDEO_RETRIES + 1}), retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                logger.warning(f"Could not fetch video {media_url}: Timeout after {attempt + 1} attempts")
                return None, None
            except requests.exceptions.ConnectionError as e:
                if attempt < MAX_VIDEO_RETRIES and self._should_retry_error(e):
                    delay = VIDEO_RETRY_DELAYS[min(attempt, len(VIDEO_RETRY_DELAYS) - 1)]
                    logger.warning(f"Video download connection error (attempt {attempt + 1}/{MAX_VIDEO_RETRIES + 1}), retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                logger.warning(f"Could not fetch video {media_url}: Connection error after {attempt + 1} attempts")
                return None, None
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response else 'unknown'
                if attempt < MAX_VIDEO_RETRIES and self._should_retry_error(e):
                    delay = VIDEO_RETRY_DELAYS[min(attempt, len(VIDEO_RETRY_DELAYS) - 1)]
                    logger.warning(f"Video download HTTP {status_code} (attempt {attempt + 1}/{MAX_VIDEO_RETRIES + 1}), retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                logger.warning(f"Could not fetch video {media_url}: HTTP {status_code} - {str(e)}")
                return None, None
            except Exception as e:
                logger.error(f"Unexpected error downloading video {media_url}: {e}", exc_info=True)
                return None, None
        
        return None, None
    
    def _get_file_extension(self, url: str, media_type: str) -> str:
        """Get file extension from URL or media type."""
        # Try to get extension from URL
        if '.' in url:
            ext = os.path.splitext(url.split('?')[0])[1]
            if ext:
                # Normalize extension to lowercase
                ext = ext.lower()
                # Validate video extensions
                if media_type == 'video':
                    # HTML5 video formats
                    valid_video_extensions = ['.mp4', '.webm', '.ogg', '.ogv', '.m4v', '.mov']
                    if ext not in valid_video_extensions:
                        # If extension not recognized, default to mp4
                        return '.mp4'
                return ext
        
        # Default extensions
        defaults = {
            'image': '.jpg',
            'video': '.mp4',  # Default to MP4 for videos (most compatible)
            'gif': '.gif',
        }
        return defaults.get(media_type, '.jpg')
    
    def _generate_video_thumbnail(
        self,
        video_path: str,
        output_dir: str
    ) -> Optional[str]:
        """Generate thumbnail for video using ffmpeg."""
        try:
            # Get base filename without extension to avoid double extension
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            thumbnail_path = os.path.join(
                output_dir,
                f"thumbnail_{base_name}.jpg"
            )
            
            # Use ffmpeg to extract frame
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-ss', DEFAULT_VIDEO_THUMBNAIL_TIME,
                '-vframes', '1',
                '-q:v', DEFAULT_THUMBNAIL_QUALITY,
                thumbnail_path,
                '-y'  # Overwrite if exists
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and os.path.exists(thumbnail_path):
                return thumbnail_path
            else:
                # Fallback: use PIL to create a placeholder
                return self._create_placeholder_thumbnail(thumbnail_path)
                
        except FileNotFoundError:
            # ffmpeg not available, create placeholder
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            thumbnail_path = os.path.join(
                output_dir,
                f"thumbnail_{base_name}.jpg"
            )
            return self._create_placeholder_thumbnail(thumbnail_path)
        except Exception as e:
            logger.error(f"Error generating video thumbnail: {e}", exc_info=True)
            return None
    
    def _create_placeholder_thumbnail(self, path: str) -> Optional[str]:
        """Create a placeholder thumbnail image."""
        try:
            # Create a simple placeholder image
            img = Image.new('RGB', DEFAULT_PLACEHOLDER_SIZE, color='gray')
            img.save(path, 'JPEG')
            return path
        except Exception as e:
            logger.error(f"Error creating placeholder thumbnail: {e}", exc_info=True)
            return None
    
    def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        try:
            full_path = os.path.join(self.media_root, file_path)
            return os.path.getsize(full_path)
        except:
            return 0
    
    def _select_highest_quality_video(self, video_urls: List[str]) -> str:
        """
        Select highest quality video URL from list of URLs.
        
        Uses HEAD requests to determine file sizes (larger = higher quality).
        Falls back to first URL if quality detection fails.
        
        Args:
            video_urls: List of video URLs (may be single-item list)
            
        Returns:
            URL string of highest quality video
        """
        if not video_urls:
            raise ValueError("video_urls cannot be empty")
        
        if len(video_urls) == 1:
            return video_urls[0]
        
        # Try to determine quality by file size
        url_sizes = {}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
        }
        
        for url in video_urls:
            try:
                head_response = requests.head(url, timeout=5, headers=headers, allow_redirects=True)
                content_length = head_response.headers.get('Content-Length')
                if content_length:
                    url_sizes[url] = int(content_length)
            except:
                # If HEAD request fails, skip this URL
                continue
        
        if url_sizes:
            # Return URL with largest file size
            return max(url_sizes.items(), key=lambda x: x[1])[0]
        
        # Fallback to first URL if all HEAD requests failed
        return video_urls[0]
    
    def _should_retry_error(self, exception: Exception) -> bool:
        """
        Determine if an exception should trigger a retry.
        
        Args:
            exception: Exception that occurred during download
            
        Returns:
            True if error is retryable, False otherwise
        """
        import requests
        
        # Retryable errors
        if isinstance(exception, requests.exceptions.Timeout):
            return True
        if isinstance(exception, requests.exceptions.ConnectionError):
            return True
        if isinstance(exception, requests.exceptions.HTTPError):
            # Retry 5xx server errors
            if exception.response and exception.response.status_code >= 500:
                return True
        
        # Non-retryable errors
        return False

