"""
Content fetcher interface and implementations for Twitter scraping.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from twitter.models import TwitterProfile
from twitter.services import TwitterScraper, TwikitScraper


class FetcherError(Exception):
    """Base exception for fetcher errors."""
    pass


class CredentialError(FetcherError):
    """Invalid or expired credentials."""
    pass


class RateLimitError(FetcherError):
    """Twitter rate limit exceeded."""
    pass


class NetworkError(FetcherError):
    """Network connectivity issue."""
    pass


class ContentFetcher(ABC):
    """Base interface for fetching content from Twitter."""
    
    def __init__(self, profile: TwitterProfile):
        """
        Initialize fetcher with user's Twitter profile.
        
        Args:
            profile: TwitterProfile instance with credentials
        """
        self.profile = profile
        self.credentials = profile.get_credentials()
        if not self.credentials:
            raise CredentialError("No credentials available for profile")
    
    @abstractmethod
    def fetch_bookmarks(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch user's bookmarked tweets.
        
        Args:
            max_items: Maximum number of bookmarks to fetch
            
        Returns:
            List of tweet dictionaries
            
        Raises:
            CredentialError: If credentials are invalid
            RateLimitError: If rate limit is hit
            NetworkError: If network request fails
        """
        pass
    
    @abstractmethod
    def fetch_home_timeline(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch tweets from user's home timeline.
        
        Args:
            max_items: Maximum number of tweets to fetch
            
        Returns:
            List of tweet dictionaries
        """
        pass
    
    @abstractmethod
    def fetch_list_tweets(self, list_id: str, max_items: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch tweets from a specific Twitter list.
        
        Args:
            list_id: Twitter list ID
            max_items: Maximum number of tweets to fetch
            
        Returns:
            List of tweet dictionaries
        """
        pass
    
    @abstractmethod
    def close(self):
        """
        Clean up resources (close browser, connections, etc.).
        Must be called after fetching is complete.
        """
        pass
    
    def validate_credentials(self) -> bool:
        """
        Validate that credentials are valid.
        
        Returns:
            bool: True if credentials are valid
        """
        return self.credentials is not None and 'username' in self.credentials


class TwitterScraperFetcher(ContentFetcher):
    """Fetcher using TwitterScraper (Playwright/Selenium)."""
    
    def __init__(self, profile: TwitterProfile, use_playwright: bool = True):
        super().__init__(profile)
        self.use_playwright = use_playwright
        self.scraper = None
    
    def _init_scraper(self):
        """Initialize the scraper if not already initialized."""
        if not self.scraper:
            self.scraper = TwitterScraper(
                username=self.credentials.get('username'),
                password=self.credentials.get('password'),
                cookies=self.credentials.get('cookies'),
                use_playwright=self.use_playwright
            )
    
    def fetch_bookmarks(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """Fetch bookmarks using TwitterScraper."""
        try:
            self._init_scraper()
            if not self.scraper.driver and not self.scraper.login():
                raise CredentialError("Failed to login to Twitter")
            
            bookmarks = self.scraper.get_bookmarks(max_bookmarks=max_items)
            return bookmarks
        except Exception as e:
            if "login" in str(e).lower() or "credential" in str(e).lower():
                raise CredentialError(f"Credential error: {e}") from e
            elif "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(f"Rate limit error: {e}") from e
            else:
                raise NetworkError(f"Network error: {e}") from e
    
    def fetch_home_timeline(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """Fetch home timeline using TwitterScraper."""
        try:
            self._init_scraper()
            if not self.scraper.driver and not self.scraper.login():
                raise CredentialError("Failed to login to Twitter")
            
            timeline = self.scraper.get_home_timeline(max_tweets=max_items)
            return timeline
        except Exception as e:
            if "login" in str(e).lower() or "credential" in str(e).lower():
                raise CredentialError(f"Credential error: {e}") from e
            elif "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(f"Rate limit error: {e}") from e
            else:
                raise NetworkError(f"Network error: {e}") from e
    
    def fetch_list_tweets(self, list_id: str, max_items: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch tweets from a Twitter list.
        Note: TwitterScraper doesn't have a direct list method, so this would need
        to be implemented or we'd use ListsService. For now, raise NotImplementedError.
        """
        # This would need to integrate with ListsService or implement list fetching
        # For now, we'll raise NotImplementedError and implement it when needed
        raise NotImplementedError("List fetching not yet implemented for TwitterScraperFetcher")
    
    def close(self):
        """Close browser/scraper resources."""
        if self.scraper:
            try:
                self.scraper.close()
            except Exception:
                pass
            finally:
                self.scraper = None


class TwikitScraperFetcher(ContentFetcher):
    """Fetcher using TwikitScraper (API-based)."""
    
    def __init__(self, profile: TwitterProfile):
        super().__init__(profile)
        self.scraper = None
    
    def _init_scraper(self):
        """Initialize the scraper if not already initialized."""
        if not self.scraper:
            self.scraper = TwikitScraper(
                username=self.credentials.get('username'),
                password=self.credentials.get('password'),
                cookies=self.credentials.get('cookies')
            )
    
    def fetch_bookmarks(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """Fetch bookmarks using TwikitScraper."""
        try:
            self._init_scraper()
            if not self.scraper.client and not self.scraper.login():
                raise CredentialError("Failed to login with Twikit")
            
            bookmarks = self.scraper.get_bookmarks(max_bookmarks=max_items)
            return bookmarks
        except Exception as e:
            if "login" in str(e).lower() or "credential" in str(e).lower():
                raise CredentialError(f"Credential error: {e}") from e
            elif "rate limit" in str(e).lower() or "429" in str(e):
                raise RateLimitError(f"Rate limit error: {e}") from e
            else:
                raise NetworkError(f"Network error: {e}") from e
    
    def fetch_home_timeline(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch home timeline using TwikitScraper.
        Note: TwikitScraper may not have this method, so we'll need to check.
        """
        # TwikitScraper may not have get_home_timeline, so raise NotImplementedError for now
        raise NotImplementedError("Home timeline fetching not yet implemented for TwikitScraperFetcher")
    
    def fetch_list_tweets(self, list_id: str, max_items: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch tweets from a Twitter list using TwikitScraper.
        Note: This would need to be implemented based on Twikit API.
        """
        raise NotImplementedError("List fetching not yet implemented for TwikitScraperFetcher")
    
    def close(self):
        """Close scraper resources."""
        if self.scraper:
            try:
                if hasattr(self.scraper, 'close'):
                    self.scraper.close()
            except Exception:
                pass
            finally:
                self.scraper = None

