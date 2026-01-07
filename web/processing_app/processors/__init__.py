"""
Content processors for different content types.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from processing_app.models import ContentProcessingJob


class ProcessingError(Exception):
    """Base exception for processing errors."""
    
    def __init__(self, message: str, retryable: bool = True, job: ContentProcessingJob = None):
        self.message = message
        self.retryable = retryable
        self.job = job
        super().__init__(self.message)


class CredentialError(ProcessingError):
    """Invalid or expired credentials."""
    def __init__(self, message: str, job: ContentProcessingJob = None):
        super().__init__(message, retryable=False, job=job)


class RateLimitError(ProcessingError):
    """Twitter rate limit hit."""
    def __init__(self, message: str, job: ContentProcessingJob = None):
        super().__init__(message, retryable=True, job=job)


class NetworkError(ProcessingError):
    """Network connectivity issues."""
    def __init__(self, message: str, job: ContentProcessingJob = None):
        super().__init__(message, retryable=True, job=job)


class ValidationError(ProcessingError):
    """Job validation failed."""
    def __init__(self, message: str, job: ContentProcessingJob = None):
        super().__init__(message, retryable=False, job=job)


class BaseProcessor(ABC):
    """Base interface for all content processors."""
    
    @abstractmethod
    def process(self, job: ContentProcessingJob) -> Dict[str, Any]:
        """
        Process content for a given job.
        
        Args:
            job: ContentProcessingJob instance to process
            
        Returns:
            Dict with processing results:
            - items_processed: int - Number of items processed
            - success: bool - Whether processing succeeded
            - metadata: dict - Additional processing metadata
            
        Raises:
            ProcessingError: If processing fails (will trigger retry)
        """
        pass
    
    @abstractmethod
    def validate_job(self, job: ContentProcessingJob) -> bool:
        """
        Validate that job can be processed.
        
        Args:
            job: ContentProcessingJob to validate
            
        Returns:
            bool: True if job is valid
            
        Raises:
            ValidationError: If validation fails with specific error message
        """
        pass
    
    def get_retry_delays(self) -> list:
        """
        Get retry delay intervals in seconds.
        
        Returns:
            list: [300, 900, 1800, 3600, 7200] (5min, 15min, 30min, 1h, 2h)
        """
        return [300, 900, 1800, 3600, 7200]


# Import concrete processor implementations
# These imports are done at the end to avoid circular import issues
# The processor modules import BaseProcessor and exceptions from this __init__.py
from processing_app.processors.bookmark_processor import BookmarkProcessor
from processing_app.processors.curated_feed_processor import CuratedFeedProcessor
from processing_app.processors.list_processor import ListProcessor

__all__ = [
    'BaseProcessor',
    'ProcessingError',
    'CredentialError',
    'RateLimitError',
    'NetworkError',
    'ValidationError',
    'BookmarkProcessor',
    'CuratedFeedProcessor',
    'ListProcessor',
]

