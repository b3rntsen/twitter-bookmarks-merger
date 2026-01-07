"""
Django-Q tasks for content processing.
"""
import logging
import asyncio
from django.utils import timezone
from processing_app.models import ContentProcessingJob
from processing_app.processors import (
    BookmarkProcessor,
    CuratedFeedProcessor,
    ListProcessor,
    ProcessingError,
    CredentialError,
    ValidationError
)
from processing_app.retry_handler import RetryHandler
from processing_app.models import DailyContentSnapshot

logger = logging.getLogger(__name__)


def _save_job_safe(job, **kwargs):
    """
    Safely save a job, ensuring we're in a sync context.
    """
    try:
        # Check if we're in an async context
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, need to run in a thread
            import threading
            def save_in_thread():
                for key, value in kwargs.items():
                    setattr(job, key, value)
                job.save(update_fields=list(kwargs.keys()))
            thread = threading.Thread(target=save_in_thread)
            thread.start()
            thread.join()
        else:
            # We're in sync context, can save directly
            for key, value in kwargs.items():
                setattr(job, key, value)
            job.save(update_fields=list(kwargs.keys()))
    except RuntimeError:
        # No event loop, we're in sync context
        for key, value in kwargs.items():
            setattr(job, key, value)
        job.save(update_fields=list(kwargs.keys()))


def process_content_job(job_id: int):
    """
    Process a content processing job.
    
    This is the main task function that Django-Q calls to process jobs.
    
    Args:
        job_id: ID of ContentProcessingJob to process
    """
    try:
        # Get job
        job = ContentProcessingJob.objects.get(id=job_id)
        logger.info(f"[TASK] Processing job {job_id} (type: {job.content_type}, user: {job.user.username}, date: {job.processing_date})")
        
        # Check if job is already completed or running
        if job.status in ['completed', 'running']:
            logger.warning(f"[TASK] Job {job_id} is already {job.status}, skipping")
            return
        
        # Get appropriate processor
        logger.info(f"[TASK] Getting processor for content type '{job.content_type}' for job {job_id}")
        processor = _get_processor(job.content_type)
        
        if not processor:
            error_msg = f"Unknown content type: {job.content_type}"
            logger.error(f"[TASK] {error_msg} for job {job_id}")
            _save_job_safe(job, status='failed', error_message=error_msg)
            return
        
        # Process job
        try:
            logger.info(f"[TASK] Calling processor.process() for job {job_id}")
            result = processor.process(job)
            
            # Update job status after successful processing
            # Use safe save to ensure we're in sync context
            _save_job_safe(
                job,
                status='completed',
                completed_at=timezone.now(),
                items_processed=result.get('items_processed', 0)
            )
            
            # Update daily snapshot
            logger.info(f"[TASK] Updating daily snapshot for job {job_id}")
            _update_daily_snapshot(job)
            
            logger.info(
                f"[TASK] Job {job_id} completed successfully. "
                f"Processed {result.get('items_processed', 0)} items"
            )
            
        except CredentialError as e:
            # Credential errors are not retryable
            logger.error(f"[TASK] Job {job_id} failed with credential error: {e.message}")
            _save_job_safe(job, status='failed', error_message=e.message)
            
        except ValidationError as e:
            # Validation errors are not retryable
            logger.error(f"[TASK] Job {job_id} failed validation: {e.message}")
            _save_job_safe(job, status='failed', error_message=e.message)
            
        except ProcessingError as e:
            # Processing errors may be retryable
            logger.error(f"[TASK] Job {job_id} failed: {e.message}")
            
            # Refresh job from DB to ensure we have latest state
            job.refresh_from_db()
            
            if e.retryable and RetryHandler.should_retry(job):
                # Check if we should bail out after retry 2 (for rate limits)
                if job.retry_count >= 2 and "rate limit" in str(e).lower():
                    logger.warning(f"[TASK] Job {job_id} hit rate limit after {job.retry_count} retries, bailing out")
                    _save_job_safe(job, status='failed', error_message=f"{e.message} (Bailed out after retry 2 due to rate limit)")
                else:
                    # Schedule retry
                    if RetryHandler.schedule_retry(job):
                        logger.info(f"[TASK] Job {job_id} scheduled for retry (attempt {job.retry_count})")
                    else:
                        logger.warning(f"[TASK] Job {job_id} exceeded max retries")
                        _save_job_safe(job, status='failed')
            else:
                # Not retryable or max retries exceeded
                _save_job_safe(job, status='failed', error_message=e.message)
                
        except Exception as e:
            # Unexpected errors
            import traceback
            error_msg = str(e)
            error_traceback = traceback.format_exc()
            
            logger.error(f"[TASK] Job {job_id} failed with unexpected error: {error_msg}")
            logger.error(f"[TASK] Traceback: {error_traceback}")
            
            _save_job_safe(job, status='failed', error_message=error_msg, error_traceback=error_traceback[:5000])
            
            # Try to schedule retry if appropriate
            if RetryHandler.should_retry(job):
                RetryHandler.schedule_retry(job)
    
    except ContentProcessingJob.DoesNotExist:
        logger.error(f"[TASK] Job {job_id} not found")
    except Exception as e:
        logger.error(f"[TASK] Unexpected error processing job {job_id}: {e}", exc_info=True)


def _get_processor(content_type: str):
    """Get the appropriate processor for a content type."""
    processors = {
        'bookmarks': BookmarkProcessor,
        'curated_feed': CuratedFeedProcessor,
        'lists': ListProcessor,
    }
    processor_class = processors.get(content_type)
    if processor_class:
        return processor_class()
    return None


def _update_daily_snapshot(job: ContentProcessingJob):
    """
    Update or create DailyContentSnapshot for the job's processing date.
    
    Args:
        job: ContentProcessingJob that was processed
    """
    snapshot, created = DailyContentSnapshot.objects.get_or_create(
        user=job.user,
        twitter_profile=job.twitter_profile,
        processing_date=job.processing_date,
        defaults={
            'bookmark_count': 0,
            'curated_feed_count': 0,
            'list_count': 0,
            'total_tweet_count': 0,
            'all_jobs_completed': False,
        }
    )
    
    # Update counts based on content type
    if job.content_type == 'bookmarks':
        snapshot.bookmark_count = job.items_processed
    elif job.content_type == 'curated_feed':
        snapshot.curated_feed_count = job.items_processed
    elif job.content_type == 'lists':
        snapshot.list_count = job.items_processed
    
    # Update total tweet count (sum of all content types)
    snapshot.total_tweet_count = (
        snapshot.bookmark_count +
        snapshot.curated_feed_count +
        snapshot.list_count
    )
    
    # Check if all jobs are completed for this date
    all_jobs = ContentProcessingJob.objects.filter(
        user=job.user,
        twitter_profile=job.twitter_profile,
        processing_date=job.processing_date
    )
    
    completed_jobs = all_jobs.filter(status='completed')
    snapshot.all_jobs_completed = (
        completed_jobs.count() == all_jobs.count() and
        all_jobs.count() > 0
    )
    
    if snapshot.all_jobs_completed:
        snapshot.last_processed_at = timezone.now()
    
    snapshot.save()


def job_completion_hook(task):
    """
    Django-Q hook that runs after a task completes (success or failure).
    
    Django-Q passes the task result as the argument.
    """
    try:
        # Django-Q passes the task result
        if hasattr(task, 'success'):
            if task.success:
                logger.info(f"[HOOK] Task {getattr(task, 'id', 'unknown')} completed successfully.")
            else:
                logger.error(f"[HOOK] Task {getattr(task, 'id', 'unknown')} failed: {getattr(task, 'result', 'unknown error')}")
        else:
            # Fallback for different task formats
            logger.info(f"[HOOK] Task completed: {task}")
    except Exception as e:
        logger.error(f"[HOOK] Error in job_completion_hook: {e}", exc_info=True)
    
    # The process_content_job already updates the ContentProcessingJob status.
    # This hook is just for logging.

