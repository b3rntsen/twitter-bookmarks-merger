"""
Processor for Twitter lists content type.
"""
import logging
from datetime import date
from django.utils import timezone
from typing import Dict, Any
from processing_app.models import ContentProcessingJob
from processing_app.processors import BaseProcessor, ProcessingError, CredentialError, ValidationError
from lists_app.services import ListsService
from lists_app.event_service import EventService
from lists_app.models import TwitterList, ListTweet, Event
from decouple import config

logger = logging.getLogger(__name__)


class ListProcessor(BaseProcessor):
    """Processes Twitter lists for a user."""
    
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
        if job.content_type != 'lists':
            raise ValidationError(
                f"Job {job.id} validation failed: content_type is '{job.content_type}', expected 'lists'",
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
        
        # Check user has at least one Twitter list
        # If no lists are found, attempt to sync them automatically
        if not TwitterList.objects.filter(twitter_profile=job.twitter_profile).exists():
            logger.warning(
                f"[LISTS] No Twitter lists found for twitter_profile {job.twitter_profile.id} in job {job.id}. "
                "Attempting to sync lists automatically..."
            )
            
            # Attempt to sync lists automatically
            try:
                self._attempt_list_sync(job.twitter_profile)
                
                # Check again after sync attempt
                if not TwitterList.objects.filter(twitter_profile=job.twitter_profile).exists():
                    logger.warning(
                        f"[LISTS] No lists found after sync attempt for twitter_profile {job.twitter_profile.id} in job {job.id}. "
                        "Job will proceed but may process 0 items."
                    )
                    # Don't fail validation - let process() handle the "no lists" case gracefully
            except Exception as e:
                logger.warning(
                    f"[LISTS] Failed to sync lists automatically for twitter_profile {job.twitter_profile.id} in job {job.id}: {e}. "
                    "Job will proceed but may process 0 items."
                )
                # Don't fail validation - let process() handle the "no lists" case gracefully
        
        return True
    
    def _attempt_list_sync(self, twitter_profile) -> int:
        """
        Attempt to sync Twitter lists for a profile.
        
        Args:
            twitter_profile: TwitterProfile instance to sync lists for
            
        Returns:
            Number of lists synced (0 if sync failed or no lists found)
        """
        lists_service = None
        try:
            logger.info(f"[LISTS] Attempting to sync lists for twitter_profile {twitter_profile.id}")
            
            # Use Playwright in production, Selenium otherwise
            use_playwright = config('USE_PLAYWRIGHT', default='False').lower() == 'true'
            
            lists_service = ListsService(twitter_profile, use_playwright=use_playwright)
            
            # Fetch lists from Twitter
            twitter_lists = lists_service.get_user_lists()
            
            if not twitter_lists:
                logger.info(f"[LISTS] No lists found on Twitter for twitter_profile {twitter_profile.id}")
                return 0
            
            logger.info(f"[LISTS] Found {len(twitter_lists)} lists on Twitter for twitter_profile {twitter_profile.id}")
            
            # Close scraper before database operations
            lists_service.close()
            lists_service = None
            
            # Small delay to ensure async context is cleared
            import time
            time.sleep(1)
            
            # Sync lists to database
            # Create a single service instance for database operations (scraper won't be initialized)
            sync_service = ListsService(twitter_profile, use_playwright=False)
            synced_count = 0
            skipped_count = 0
            for list_data in twitter_lists:
                # Validate that list_id exists
                list_id = list_data.get('list_id')
                if not list_id:
                    logger.warning(f"[LISTS] Skipping list '{list_data.get('list_name', 'Unknown')}' - no list_id found")
                    skipped_count += 1
                    continue
                
                try:
                    sync_service.sync_list(
                        list_id=list_id,
                        list_name=list_data.get('list_name', 'Unknown List'),
                        list_url=list_data.get('list_url')
                    )
                    synced_count += 1
                    logger.info(f"[LISTS] Synced list '{list_data.get('list_name')}' (ID: {list_id})")
                except Exception as e:
                    logger.error(f"[LISTS] Error syncing list {list_id}: {e}", exc_info=True)
                    continue
            
            if skipped_count > 0:
                logger.warning(f"[LISTS] Skipped {skipped_count} list(s) due to missing list_id")
            
            # Close sync service (safe even if scraper wasn't initialized)
            try:
                sync_service.close()
            except Exception:
                pass
            
            logger.info(f"[LISTS] Successfully synced {synced_count} list(s) for twitter_profile {twitter_profile.id}")
            return synced_count
            
        except Exception as e:
            logger.error(f"[LISTS] Error during list sync for twitter_profile {twitter_profile.id}: {e}", exc_info=True)
            return 0
        finally:
            # Ensure scraper is closed
            if lists_service:
                try:
                    lists_service.close()
                except Exception:
                    pass
    
    def process(self, job: ContentProcessingJob) -> Dict[str, Any]:
        """
        Process lists for a given job.
        
        Args:
            job: ContentProcessingJob instance to process
            
        Returns:
            Dict with processing results
        """
        # Validate job (raises ValidationError with specific message if invalid)
        self.validate_job(job)
        
        logger.info(f"[LISTS] Starting job {job.id} for user {job.user.username} on {job.processing_date}")
        
        # Pre-fetch related objects to avoid async context issues
        twitter_profile = job.twitter_profile
        
        # Update job status
        job.status = 'running'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
        
        lists_service = None
        try:
            # Get user's Twitter lists
            logger.info(f"[LISTS] Fetching user's Twitter lists for job {job.id}")
            twitter_lists = TwitterList.objects.filter(twitter_profile=twitter_profile)
            
            if not twitter_lists.exists():
                # No lists found - still successful
                # Don't save here - let the task handler save after we return
                return {
                    'items_processed': 0,
                    'success': True,
                    'metadata': {'message': 'No lists found'}
                }
            
            # Initialize ListsService for fetching tweets
            logger.info(f"[LISTS] Initializing ListsService for {twitter_lists.count()} lists for job {job.id}")
            lists_service = ListsService(twitter_profile, use_playwright=True)
            
            # First, fetch all tweets for all lists (collect in memory)
            # This ensures we're done with Playwright before doing database operations
            list_tweets_data = {}  # {twitter_list: [tweet_data, ...]}
            
            for idx, twitter_list in enumerate(twitter_lists, 1):
                try:
                    max_tweets = config('LIST_MAX_TWEETS', default=500, cast=int)
                    logger.info(f"[LISTS] Fetching tweets for list {idx}/{twitter_lists.count()}: '{twitter_list.list_name}' (ID: {twitter_list.list_id}) for job {job.id}")
                    tweets_data = lists_service.get_list_tweets(twitter_list, max_tweets=max_tweets)
                    if tweets_data:
                        logger.info(f"[LISTS] Fetched {len(tweets_data)} tweets from list '{twitter_list.list_name}' for job {job.id}")
                        list_tweets_data[twitter_list] = tweets_data
                    else:
                        logger.info(f"[LISTS] No tweets found for list '{twitter_list.list_name}' for job {job.id}")
                except Exception as e:
                    # Log error but continue with other lists
                    logger.error(f"[LISTS] Error fetching tweets for list {twitter_list.list_id}: {e}", exc_info=True)
                    continue
            
            # Close ListsService immediately after fetching to exit async context
            logger.info(f"[LISTS] Closing ListsService for job {job.id}")
            lists_service.close()
            lists_service = None
            
            logger.info(f"[LISTS] Fetched tweets from {len(list_tweets_data)}/{twitter_lists.count()} lists for job {job.id}")
            
            # Now process all fetched data (database operations outside async context)
            total_tweets_processed = 0
            lists_processed = 0
            
            from twitter.models import Tweet
            from bookmarks_app.services import BookmarkService
            
            bookmark_service = BookmarkService(job.twitter_profile)
            
            # Process each list's tweets
            logger.info(f"[LISTS] Storing tweets to database for job {job.id}")
            for list_idx, (twitter_list, tweets_data) in enumerate(list_tweets_data.items(), 1):
                try:
                    logger.info(f"[LISTS] Processing list {list_idx}/{len(list_tweets_data)}: '{twitter_list.list_name}' ({len(tweets_data)} tweets) for job {job.id}")
                    stored_tweets = []
                    
                    for tweet_idx, tweet_data in enumerate(tweets_data, 1):
                        if tweet_idx % 50 == 0 or tweet_idx == len(tweets_data):
                            logger.info(f"[LISTS] Storing tweet {tweet_idx}/{len(tweets_data)} from list '{twitter_list.list_name}' for job {job.id}")
                        # Parse timestamp
                        created_at = bookmark_service._parse_timestamp(tweet_data.get('created_at'))
                        
                        # Get or create tweet
                        tweet, created = Tweet.objects.get_or_create(
                            tweet_id=tweet_data['tweet_id'],
                            defaults={
                                'twitter_profile': job.twitter_profile,
                                'author_username': tweet_data.get('author_username', ''),
                                'author_display_name': tweet_data.get('author_display_name', ''),
                                'author_profile_image_url': tweet_data.get('author_profile_image_url', ''),
                                'text_content': tweet_data.get('text_content', ''),
                                'created_at': created_at,
                                'like_count': tweet_data.get('like_count', 0),
                                'retweet_count': tweet_data.get('retweet_count', 0),
                                'reply_count': tweet_data.get('reply_count', 0),
                                'is_bookmark': False,
                                'raw_data': tweet_data,
                            }
                        )
                        
                        # Update processing_date (used as seen_date for lists)
                        tweet.processing_date = job.processing_date
                        tweet.save(update_fields=['processing_date'])
                        
                        # Create or update ListTweet - save immediately for incremental progress
                        list_tweet, _ = ListTweet.objects.get_or_create(
                            twitter_list=twitter_list,
                            tweet=tweet,
                            defaults={
                                'seen_date': job.processing_date,
                            }
                        )
                        list_tweet.seen_date = job.processing_date
                        list_tweet.save(update_fields=['seen_date'])
                        
                        stored_tweets.append(tweet)
                        total_tweets_processed += 1
                        
                        # Update job progress incrementally (every 10 tweets to avoid too many DB writes)
                        # Note: We're in sync context after closing ListsService, so save is safe
                        if total_tweets_processed % 10 == 0:
                            job.items_processed = total_tweets_processed
                            try:
                                job.save(update_fields=['items_processed'])
                            except Exception as save_error:
                                # If save fails due to async context, log and continue
                                logger.warning(f"[LISTS] Could not save job progress: {save_error}")
                    
                    # After all tweets are stored, generate events incrementally
                    # Process events in batches to show progress
                    logger.info(f"[LISTS] Generating events for list '{twitter_list.list_name}' ({len(stored_tweets)} tweets) for job {job.id}")
                    event_service = EventService()
                    # Filter tweets by seen_date (processing_date), but EventService will determine
                    # the actual event_date from the tweet content/timestamps
                    events = event_service.group_tweets_into_events(
                        twitter_list=twitter_list,
                        event_date=job.processing_date,  # Used to filter ListTweets by seen_date
                        min_tweets=3
                    )
                    # Note: Event.event_date should be set by EventService based on tweet.created_at
                    # dates, not processing_date. The event_date represents when the event happened,
                    # not when it was processed.
                    
                    # Events are already created by group_tweets_into_events
                    events_created = len(events)
                    logger.info(f"[LISTS] Created {events_created} events for list '{twitter_list.list_name}' for job {job.id}")
                    
                    lists_processed += 1
                    
                except Exception as e:
                    # Log error but continue with other lists
                    logger.error(f"[LISTS] Error processing list {twitter_list.list_id}: {e}", exc_info=True)
                    continue
            
            logger.info(f"[LISTS] Job {job.id} completed successfully: {total_tweets_processed} tweets from {lists_processed} lists")
            
            # Don't save job status here - let the task handler save after we return
            # The ListsService is already closed, but to be safe, let the task handler handle it
            
            return {
                'items_processed': total_tweets_processed,
                'success': True,
                'metadata': {
                    'lists_processed': lists_processed,
                    'total_lists': twitter_lists.count()
                }
            }
            
        except Exception as e:
            # Handle errors
            import traceback
            error_msg = str(e)
            error_traceback = traceback.format_exc()
            
            logger.error(f"[LISTS] Unexpected error for job {job.id}: {error_msg}", exc_info=True)
            
            # Ensure we're out of async context before saving
            if lists_service:
                try:
                    lists_service.close()
                except Exception:
                    pass
                lists_service = None
                # Small delay to ensure async context is fully exited
                import time
                time.sleep(0.1)
            
            # Let the task handler save the job status - just raise the exception
            raise ProcessingError(error_msg, retryable=True, job=job) from e
            
        finally:
            # Always close lists_service
            if lists_service:
                try:
                    lists_service.close()
                except Exception:
                    pass

