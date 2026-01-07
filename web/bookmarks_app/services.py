"""
Bookmark service for storing and managing Twitter bookmarks.
"""
from typing import List, Dict, Optional
from django.utils import timezone
from datetime import datetime
from twitter.models import TwitterProfile, Tweet, TweetThread, TweetMedia, TweetReply
from bookmarks_app.media_handler import MediaDownloader
import re
import logging

logger = logging.getLogger(__name__)

# Constants
MAX_TWEET_TEXT_LENGTH = 500
DEFAULT_THREAD_POSITION = 0
DEFAULT_ENGAGEMENT_COUNT = 0


class BookmarkService:
    """
    Service for storing and managing Twitter bookmarks.
    
    This service handles the complete lifecycle of bookmark storage:
    - Processing and expanding URLs
    - Creating/updating tweet records
    - Downloading and storing media
    - Managing thread relationships
    - Sanitizing HTML content
    """
    
    def __init__(self, twitter_profile: TwitterProfile):
        """
        Initialize the BookmarkService.
        
        Args:
            twitter_profile: The TwitterProfile instance to associate bookmarks with
        """
        self.twitter_profile = twitter_profile
        self.media_downloader = MediaDownloader()
    
    def store_bookmarks(self, bookmarks: List[Dict]) -> int:
        """
        Store bookmarks in the database.
        
        Processes each bookmark by:
        1. Expanding t.co URLs to full URLs
        2. Creating or updating tweet records
        3. Downloading and storing media files
        4. Sanitizing HTML content
        5. Managing thread relationships
        
        Args:
            bookmarks: List of bookmark dictionaries containing tweet data
            
        Returns:
            Number of newly created bookmarks (not updated ones)
        """
        stored_count = 0
        
        for bookmark_data in bookmarks:
            try:
                tweet, was_created = self._process_and_store_bookmark(bookmark_data)
                if tweet and was_created:
                    stored_count += 1
            except Exception as e:
                tweet_id = bookmark_data.get('tweet_id', 'unknown')
                logger.error(f"Error storing bookmark {tweet_id}: {e}", exc_info=True)
                continue
        
        self._update_sync_timestamp()
        return stored_count
    
    def _process_and_store_bookmark(self, bookmark_data: Dict) -> tuple:
        """
        Process a single bookmark and store it in the database.
        
        Args:
            bookmark_data: Dictionary containing tweet data
            
        Returns:
            Tuple of (Tweet instance, was_created boolean) if successful, (None, False) otherwise
        """
        # Expand t.co URLs in text content
        text_content = self._expand_urls_in_text(bookmark_data)
        
        # Create or update tweet
        tweet, created = self._create_or_update_tweet(bookmark_data, text_content)
        
        # Update existing tweet with latest data
        if not created:
            self._update_existing_tweet(tweet, bookmark_data, text_content)
        
        # Download and store media
        media_urls = bookmark_data.get('media_urls', [])
        if media_urls:
            self._store_media(tweet, media_urls)
        
        # Process and sanitize HTML content
        self._process_tweet_html(tweet, bookmark_data)
        
        # Handle thread relationships
        if bookmark_data.get('in_reply_to_tweet_id'):
            self._store_thread_relationship(
                bookmark_data['in_reply_to_tweet_id'],
                tweet.tweet_id
            )
        
        return tweet, created
    
    def _expand_urls_in_text(self, bookmark_data: Dict) -> str:
        """
        Replace t.co URLs in text with their expanded URLs.
        
        Args:
            bookmark_data: Dictionary containing tweet data with links
            
        Returns:
            Text content with expanded URLs
        """
        text_content = bookmark_data.get('text_content', '')
        links = bookmark_data.get('links', [])
        
        if not links:
            return text_content
        
        for link_info in links:
            tco_url = link_info.get('tco_url', '')
            expanded_url = link_info.get('expanded_url', '')
            
            if tco_url and expanded_url and tco_url in text_content:
                text_content = text_content.replace(tco_url, expanded_url)
        
        return text_content
    
    def _create_or_update_tweet(self, bookmark_data: Dict, text_content: str) -> tuple:
        """
        Create a new tweet or get existing one.
        
        Args:
            bookmark_data: Dictionary containing tweet data
            text_content: Processed text content with expanded URLs
            
        Returns:
            Tuple of (Tweet instance, created boolean)
        """
        defaults = {
            'twitter_profile': self.twitter_profile,
            'author_username': bookmark_data.get('author_username', ''),
            'author_display_name': bookmark_data.get('author_display_name', ''),
            'author_profile_image_url': bookmark_data.get('author_profile_image_url', ''),
            'author_id': bookmark_data.get('author_id', ''),
            'text_content': text_content,
            'html_content': bookmark_data.get('html_content', ''),
            'html_content_sanitized': '',  # Will be set after media is stored
            'created_at': self._parse_timestamp(bookmark_data.get('created_at')),
            'like_count': bookmark_data.get('like_count', DEFAULT_ENGAGEMENT_COUNT),
            'retweet_count': bookmark_data.get('retweet_count', DEFAULT_ENGAGEMENT_COUNT),
            'reply_count': bookmark_data.get('reply_count', DEFAULT_ENGAGEMENT_COUNT),
            'is_bookmark': True,
            'is_reply': bookmark_data.get('is_reply', False),
            'in_reply_to_tweet_id': bookmark_data.get('in_reply_to_tweet_id', ''),
            'conversation_id': bookmark_data.get('conversation_id', bookmark_data['tweet_id']),
            'thread_position': bookmark_data.get('thread_position', DEFAULT_THREAD_POSITION),
            'raw_data': bookmark_data,
        }
        
        return Tweet.objects.get_or_create(
            tweet_id=bookmark_data['tweet_id'],
            defaults=defaults
        )
    
    def _update_existing_tweet(self, tweet: Tweet, bookmark_data: Dict, text_content: str):
        """
        Update an existing tweet with latest data.
        
        Args:
            tweet: Existing Tweet instance
            bookmark_data: Dictionary containing tweet data
            text_content: Processed text content with expanded URLs
        """
        # Always update text content (may have expanded URLs or other changes)
        tweet.text_content = text_content
        
        if bookmark_data.get('author_display_name'):
            tweet.author_display_name = bookmark_data.get('author_display_name')
        
        if bookmark_data.get('author_profile_image_url'):
            tweet.author_profile_image_url = bookmark_data.get('author_profile_image_url')
        
        if bookmark_data.get('html_content'):
            tweet.html_content = bookmark_data.get('html_content')
        
        tweet.raw_data = bookmark_data
        tweet.save()
    
    def _process_tweet_html(self, tweet: Tweet, bookmark_data: Dict):
        """
        Process and sanitize HTML content for a tweet.
        
        Args:
            tweet: Tweet instance to update
            bookmark_data: Dictionary containing tweet data
        """
        html_content = bookmark_data.get('html_content', '')
        
        if html_content:
            html_content_sanitized = self._process_html_content(html_content, tweet.tweet_id)
            tweet.html_content = html_content
            tweet.html_content_sanitized = html_content_sanitized
            tweet.save()
    
    def _update_sync_timestamp(self):
        """Update the last sync timestamp for the Twitter profile."""
        self.twitter_profile.last_sync_at = timezone.now()
        self.twitter_profile.save()
    
    def _parse_timestamp(self, timestamp_str: Optional[str]) -> datetime:
        """
        Parse timestamp string to datetime object.
        
        Supports multiple timestamp formats:
        - ISO format with 'Z' suffix
        - ISO format with microseconds
        
        Args:
            timestamp_str: Timestamp string to parse, or None
            
        Returns:
            Parsed datetime object, or current time if parsing fails
        """
        if not timestamp_str:
            return timezone.now()
        
        # Try ISO format with 'Z' suffix
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
        
        # Try ISO format with microseconds
        try:
            return datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%fZ')
        except (ValueError, AttributeError):
            pass
        
        # Fallback to current time
        logger.warning(f"Could not parse timestamp '{timestamp_str}', using current time")
        return timezone.now()
    
    def _store_media(self, tweet: Tweet, media_urls: List[str]):
        """
        Download and store media files for a tweet.
        
        Media download failures are logged but don't abort processing.
        The tweet will be stored even if some media cannot be fetched.
        
        Args:
            tweet: Tweet instance to associate media with
            media_urls: List of media URLs to download
        """
        for media_url in media_urls:
            try:
                media_type = self._determine_media_type(media_url)
                
                file_path, thumbnail_path = self.media_downloader.download_media(
                    media_url=media_url,
                    tweet_id=tweet.tweet_id,
                    media_type=media_type
                )
                
                # Always save media record to preserve original URL, even if download failed
                # This allows fallback to original Twitter URL when local video is unavailable
                self._save_media_to_database(
                    tweet, media_url, media_type, file_path, thumbnail_path
                )
                
                # If file_path is None, download_media already logged the issue
                # Continue processing other media and the tweet itself
            except Exception as e:
                # Unexpected error in media handling - log but continue
                logger.warning(f"Could not store media {media_url} for tweet {tweet.tweet_id}: {e}")
                continue
    
    def _determine_media_type(self, media_url: str) -> str:
        """
        Determine media type from URL.
        
        Args:
            media_url: URL of the media file
            
        Returns:
            Media type string: 'video', 'gif', or 'image'
        """
        media_url_lower = media_url.lower()
        
        # Check for video indicators
        video_indicators = [
            'video.twimg.com',
            '.mp4',
            '.webm',
            '.ogg',
            '.ogv',
            '.m4v',
            '.mov',
            '/video/',
            'video',
        ]
        
        if any(indicator in media_url_lower for indicator in video_indicators):
            return 'video'
        elif '.gif' in media_url_lower:
            return 'gif'
        else:
            return 'image'
    
    def _save_media_to_database(
        self, 
        tweet: Tweet, 
        media_url: str, 
        media_type: str, 
        file_path: Optional[str], 
        thumbnail_path: Optional[str]
    ):
        """
        Save media information to the database.
        
        For videos, preserves original_url even when download fails (file_path is None).
        This allows fallback to original Twitter URL.
        
        Args:
            tweet: Tweet instance to associate media with
            media_url: Original URL of the media
            media_type: Type of media ('image', 'video', 'gif')
            file_path: Local file path where media is stored (None if download failed)
            thumbnail_path: Optional path to thumbnail image
        """
        defaults = {
            'media_type': media_type,
            'file_path': file_path or '',
            'thumbnail_path': thumbnail_path or '',
            'file_size': self.media_downloader.get_file_size(file_path) if file_path else 0,
        }
        
        TweetMedia.objects.get_or_create(
            tweet=tweet,
            original_url=media_url,
            defaults=defaults
        )
    
    def _process_html_content(self, html_content: str, tweet_id: str) -> str:
        """Process HTML content: rewrite media URLs to local paths and remove JavaScript."""
        try:
            from bs4 import BeautifulSoup
            from django.conf import settings
            import os
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove all script tags
            for script in soup.find_all('script'):
                script.decompose()
            
            # Remove event handlers (onclick, onload, etc.)
            for tag in soup.find_all():
                for attr in list(tag.attrs.keys()):
                    if attr.startswith('on'):
                        del tag.attrs[attr]
            
            # Rewrite image URLs to local paths
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src:
                    # Check if this is a media file we've downloaded
                    media_item = self._find_local_media(tweet_id, src)
                    if media_item:
                        # Replace with local URL
                        local_url = f"{settings.MEDIA_URL}{media_item.file_path}"
                        if 'src' in img.attrs:
                            img['src'] = local_url
                        if 'data-src' in img.attrs:
                            img['data-src'] = local_url
            
            # Rewrite video URLs
            for video in soup.find_all('video'):
                src = video.get('src')
                if src:
                    media_item = self._find_local_media(tweet_id, src)
                    if media_item:
                        video['src'] = f"{settings.MEDIA_URL}{media_item.file_path}"
                # Also check source tags
                for source in video.find_all('source'):
                    src = source.get('src')
                    if src:
                        media_item = self._find_local_media(tweet_id, src)
                        if media_item:
                            source['src'] = f"{settings.MEDIA_URL}{media_item.file_path}"
            
            # Rewrite profile picture URLs if we have them stored
            # (For now, we'll keep external URLs for profile pictures)
            
            return str(soup)
        except Exception as e:
            logger.error(f"Error processing HTML content: {e}", exc_info=True)
            # Return HTML with scripts removed as fallback
            import re
            # Remove script tags
            html = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            # Remove event handlers
            html = re.sub(r'\s+on\w+="[^"]*"', '', html)
            return html
    
    def _find_local_media(self, tweet_id: str, original_url: str):
        """Find local media file matching the original URL."""
        try:
            from twitter.models import Tweet, TweetMedia
            
            tweet = Tweet.objects.filter(tweet_id=tweet_id).first()
            if not tweet:
                return None
            
            # Try to find media by original URL
            media = TweetMedia.objects.filter(
                tweet=tweet,
                original_url__icontains=original_url.split('?')[0]  # Match without query params
            ).first()
            
            return media
        except:
            return None
    
    def _store_thread_relationship(self, parent_tweet_id: str, child_tweet_id: str):
        """Store thread relationship between tweets."""
        try:
            parent_tweet = Tweet.objects.get(tweet_id=parent_tweet_id)
            child_tweet = Tweet.objects.get(tweet_id=child_tweet_id)
            
            # Get thread order
            existing_threads = TweetThread.objects.filter(parent_tweet=parent_tweet).count()
            thread_order = existing_threads + 1
            
            TweetThread.objects.get_or_create(
                parent_tweet=parent_tweet,
                child_tweet=child_tweet,
                defaults={'thread_order': thread_order}
            )
        except Tweet.DoesNotExist:
            # Parent tweet not found yet, skip for now
            pass
        except Exception as e:
            logger.error(f"Error storing thread relationship: {e}", exc_info=True)
    
    def fetch_and_store_thread(self, tweet_id: str, scraper):
        """Fetch and store full thread for a tweet."""
        try:
            thread_tweets = scraper.get_tweet_thread(tweet_id)
            
            # Store all tweets in thread
            for i, thread_tweet_data in enumerate(thread_tweets):
                tweet, created = Tweet.objects.get_or_create(
                    tweet_id=thread_tweet_data['tweet_id'],
                    defaults={
                        'twitter_profile': self.twitter_profile,
                        'author_username': thread_tweet_data.get('author_username', ''),
                        'text_content': thread_tweet_data.get('text_content', ''),
                        'created_at': self._parse_timestamp(thread_tweet_data.get('created_at')),
                        'like_count': thread_tweet_data.get('like_count', 0),
                        'retweet_count': thread_tweet_data.get('retweet_count', 0),
                        'reply_count': thread_tweet_data.get('reply_count', 0),
                        'is_bookmark': False,  # Thread tweets are not bookmarks themselves
                        'conversation_id': thread_tweet_data.get('conversation_id', tweet_id),
                        'thread_position': i,
                        'raw_data': thread_tweet_data,
                    }
                )
                
                # Store media
                media_urls = thread_tweet_data.get('media_urls', [])
                if media_urls:
                    self._store_media(tweet, media_urls)
                
                # Store thread relationship
                if i > 0:
                    parent_tweet_id = thread_tweets[i-1]['tweet_id']
                    self._store_thread_relationship(parent_tweet_id, tweet.tweet_id)
            
            return len(thread_tweets)
        except Exception as e:
            logger.error(f"Error fetching thread for {tweet_id}: {e}", exc_info=True)
            return 0

