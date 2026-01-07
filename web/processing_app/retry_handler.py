"""
Retry handler for content processing jobs with exponential backoff.
"""
from datetime import timedelta
from django.utils import timezone
from processing_app.models import ContentProcessingJob


class RetryHandler:
    """Handles retry logic with exponential backoff for processing jobs."""
    
    # Retry delays in seconds: 5min, 15min, 30min, 60min, 2h
    RETRY_DELAYS = [300, 900, 1800, 3600, 7200]
    
    @classmethod
    def get_retry_delay(cls, retry_count: int) -> int:
        """
        Get retry delay in seconds for a given retry count.
        
        Args:
            retry_count: Current retry count (0-indexed)
            
        Returns:
            Delay in seconds, or None if max retries exceeded
        """
        if retry_count >= len(cls.RETRY_DELAYS):
            return None
        return cls.RETRY_DELAYS[retry_count]
    
    @classmethod
    def should_retry(cls, job: ContentProcessingJob) -> bool:
        """
        Check if a job should be retried.
        
        Args:
            job: ContentProcessingJob to check
            
        Returns:
            bool: True if job should be retried
        """
        if job.status != 'failed':
            return False
        
        if job.retry_count >= job.max_retries:
            return False
        
        # Check if retry delay has passed
        if job.next_retry_at:
            return timezone.now() >= job.next_retry_at
        
        return True
    
    @classmethod
    def schedule_retry(cls, job: ContentProcessingJob) -> bool:
        """
        Schedule a retry for a failed job.
        
        Args:
            job: ContentProcessingJob to schedule retry for
            
        Returns:
            bool: True if retry was scheduled, False if max retries exceeded
        """
        if job.retry_count >= job.max_retries:
            return False
        
        delay = cls.get_retry_delay(job.retry_count)
        if delay is None:
            return False
        
        job.retry_count += 1
        job.status = 'retrying'
        job.next_retry_at = timezone.now() + timedelta(seconds=delay)
        job.save(update_fields=['retry_count', 'status', 'next_retry_at'])
        
        return True
    
    @classmethod
    def get_next_retry_time(cls, retry_count: int) -> timedelta:
        """
        Get timedelta for next retry based on retry count.
        
        Args:
            retry_count: Current retry count
            
        Returns:
            timedelta for next retry, or None if max retries exceeded
        """
        delay = cls.get_retry_delay(retry_count)
        if delay is None:
            return None
        return timedelta(seconds=delay)

