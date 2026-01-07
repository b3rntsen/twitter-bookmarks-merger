"""
Processor for bookmark content type.
"""
import logging
from datetime import date
from django.utils import timezone
from typing import Dict, Any
from decouple import config
from processing_app.models import ContentProcessingJob
from processing_app.processors import BaseProcessor, ProcessingError, CredentialError, ValidationError
from processing_app.fetchers import TwitterScraperFetcher, FetcherError
from bookmarks_app.services import BookmarkService
from twitter.models import Tweet

logger = logging.getLogger(__name__)


class BookmarkProcessor(BaseProcessor):
    """Processes bookmarks for a user."""
    
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
        if job.content_type != 'bookmarks':
            raise ValidationError(
                f"Job {job.id} validation failed: content_type is '{job.content_type}', expected 'bookmarks'",
                job=job
            )
        
        if not job.twitter_profile:
            raise ValidationError(
                f"Job {job.id} validation failed: twitter_profile is missing",
                job=job
            )
        
        # Check credentials
        credentials = job.twitter_profile.get_credentials()
        if not credentials:
            raise ValidationError(
                f"Job {job.id} validation failed: no credentials found for twitter_profile {job.twitter_profile.id}",
                job=job
            )
        
        # Check processing_date is not in future
        if job.processing_date > date.today():
            raise ValidationError(
                f"Job {job.id} validation failed: processing_date {job.processing_date} is in the future",
                job=job
            )
        
        return True
    
    def process(self, job: ContentProcessingJob) -> Dict[str, Any]:
        """
        Process bookmarks for a given job.
        
        Args:
            job: ContentProcessingJob instance to process
            
        Returns:
            Dict with processing results
        """
        # Validate job (raises ValidationError with specific message if invalid)
        self.validate_job(job)
        
        logger.info(f"[BOOKMARKS] Starting job {job.id} for user {job.user.username} on {job.processing_date}")
        
        # Pre-fetch related objects to avoid async context issues
        twitter_profile = job.twitter_profile
        
        # Update job status
        job.status = 'running'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
        
        fetcher = None
        try:
            # Initialize fetcher
            logger.info(f"[BOOKMARKS] Initializing Twitter fetcher for job {job.id}")
            fetcher = TwitterScraperFetcher(twitter_profile, use_playwright=True)
            
            # Fetch bookmarks
            max_bookmarks = config('BOOKMARK_MAX_ITEMS', default=1000, cast=int)
            logger.info(f"[BOOKMARKS] Fetching bookmarks (max {max_bookmarks}) for job {job.id}")
            bookmarks = fetcher.fetch_bookmarks(max_items=max_bookmarks)
            
            # Close fetcher immediately to exit async context before database operations
            # This prevents "You cannot call this from an async context" errors
            logger.info(f"[BOOKMARKS] Closing fetcher for job {job.id}")
            fetcher.close()
            fetcher = None
            
            logger.info(f"[BOOKMARKS] Fetched {len(bookmarks) if bookmarks else 0} bookmarks for job {job.id}")
            
            if not bookmarks:
                # No bookmarks found - still successful
                # Don't save here - let the task handler save after we return
                return {
                    'items_processed': 0,
                    'success': True,
                    'metadata': {'message': 'No bookmarks found'}
                }
            
            # Store bookmarks using BookmarkService
            logger.info(f"[BOOKMARKS] Storing {len(bookmarks)} bookmarks to database for job {job.id}")
            bookmark_service = BookmarkService(twitter_profile)
            stored_count = bookmark_service.store_bookmarks(bookmarks)
            
            # Update tweets with processing_date
            logger.info(f"[BOOKMARKS] Updating processing_date for {len(bookmarks)} bookmarks for job {job.id}")
            tweet_ids = [b.get('tweet_id') for b in bookmarks if b.get('tweet_id')]
            if tweet_ids:
                Tweet.objects.filter(
                    tweet_id__in=tweet_ids,
                    twitter_profile=twitter_profile
                ).update(processing_date=job.processing_date)
            
            logger.info(f"[BOOKMARKS] Job {job.id} completed successfully: {stored_count} bookmarks stored")
            
            # Don't save job status here - let the task handler save after we return
            # The fetcher is already closed, but to be safe, let the task handler handle it
            
            return {
                'items_processed': stored_count,
                'success': True,
                'metadata': {
                    'total_fetched': len(bookmarks),
                    'newly_stored': stored_count
                }
            }
            
        except FetcherError as e:
            # Handle fetcher errors
            error_msg = str(e)
            logger.error(f"[BOOKMARKS] Fetcher error for job {job.id}: {error_msg}")
            
            # Ensure we're out of async context before saving
            if fetcher:
                try:
                    fetcher.close()
                except Exception:
                    pass
                fetcher = None
                # Small delay to ensure async context is fully exited
                import time
                time.sleep(0.1)
            
            # Save job status - let the exception propagate and let the task handler save it
            # We'll just raise the error and let tasks.py handle the saving
            if isinstance(e, CredentialError):
                raise CredentialError(error_msg, job=job) from e
            else:
                raise ProcessingError(error_msg, retryable=True, job=job) from e
                
        except Exception as e:
            # Handle other errors
            import traceback
            error_msg = str(e)
            error_traceback = traceback.format_exc()
            
            logger.error(f"[BOOKMARKS] Unexpected error for job {job.id}: {error_msg}", exc_info=True)
            
            # Ensure we're out of async context before saving
            if fetcher:
                try:
                    fetcher.close()
                except Exception:
                    pass
                fetcher = None
                # Small delay to ensure async context is fully exited
                import time
                time.sleep(0.1)
            
            # Save job status - let the exception propagate and let the task handler save it
            raise ProcessingError(error_msg, retryable=True, job=job) from e
            
        finally:
            # Fetcher is already closed above, but ensure cleanup if there was an error
            if fetcher:
                try:
                    fetcher.close()
                except Exception:
                    pass

