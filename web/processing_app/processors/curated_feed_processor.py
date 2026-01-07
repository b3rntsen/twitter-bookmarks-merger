"""
Processor for curated feed content type.
"""
import logging
from datetime import date
from django.utils import timezone
from typing import Dict, Any
from processing_app.models import ContentProcessingJob
from processing_app.processors import BaseProcessor, ProcessingError, CredentialError, ValidationError
from processing_app.fetchers import TwitterScraperFetcher, FetcherError
from bookmarks_app.services import BookmarkService
from bookmarks_app.categorization_service import TweetCategorizationService
from bookmarks_app.models import CuratedFeed, TweetCategory, CategorizedTweet
from twitter.models import Tweet
from decouple import config

logger = logging.getLogger(__name__)


class CuratedFeedProcessor(BaseProcessor):
    """Processes curated feed (home timeline) for a user."""
    
    def __init__(self, ai_provider: str = None):
        """
        Initialize processor.
        
        Args:
            ai_provider: 'anthropic' or 'openai', defaults to config value
        """
        self.ai_provider = ai_provider or config('AI_PROVIDER', default='anthropic')
    
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
        if job.content_type != 'curated_feed':
            raise ValidationError(
                f"Job {job.id} validation failed: content_type is '{job.content_type}', expected 'curated_feed'",
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
        Process curated feed for a given job.
        
        Args:
            job: ContentProcessingJob instance to process
            
        Returns:
            Dict with processing results
        """
        # Validate job (raises ValidationError with specific message if invalid)
        self.validate_job(job)
        
        logger.info(f"[CURATED_FEED] Starting job {job.id} for user {job.user.username} on {job.processing_date}")
        
        # Pre-fetch related objects to avoid async context issues
        user = job.user
        twitter_profile = job.twitter_profile
        
        # Update job status
        job.status = 'running'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'started_at'])
        
        fetcher = None
        try:
            # Initialize fetcher
            logger.info(f"[CURATED_FEED] Initializing Twitter fetcher for job {job.id}")
            fetcher = TwitterScraperFetcher(twitter_profile, use_playwright=True)
            
            # Fetch home timeline
            num_tweets = config('CURATED_FEED_NUM_TWEETS', default=100, cast=int)
            logger.info(f"[CURATED_FEED] Fetching home timeline (max {num_tweets} tweets) for job {job.id}")
            tweets_data = fetcher.fetch_home_timeline(max_items=num_tweets)
            
            # Close fetcher immediately to exit async context before database operations
            # This prevents "You cannot call this from an async context" errors
            logger.info(f"[CURATED_FEED] Closing fetcher for job {job.id}")
            fetcher.close()
            fetcher = None
            
            logger.info(f"[CURATED_FEED] Fetched {len(tweets_data) if tweets_data else 0} tweets for job {job.id}")
            
            if not tweets_data:
                # No tweets found - still successful
                # Don't save here - let the task handler save after we return
                # The fetcher is already closed, so we should be in sync context
                # But to be safe, we'll let the task handler save
                return {
                    'items_processed': 0,
                    'success': True,
                    'metadata': {'message': 'No tweets found'}
                }
            
            # Store tweets incrementally - save each tweet immediately
            # This allows users to see tweets in "uncategorized" container while categorization is in progress
            logger.info(f"[CURATED_FEED] Storing {len(tweets_data)} tweets to database for job {job.id}")
            bookmark_service = BookmarkService(twitter_profile)
            stored_tweets = []
            
            # Create CuratedFeed record first (before categorization)
            logger.info(f"[CURATED_FEED] Creating CuratedFeed record for job {job.id}")
            curated_feed = CuratedFeed.objects.create(
                user=user,
                twitter_profile=twitter_profile,
                processing_date=job.processing_date,
                num_tweets_fetched=0,  # Will be updated as we process
                config_num_tweets=num_tweets,
                num_categories=0  # Will be updated after categorization
            )
            
            # Create "Uncategorized" category to hold tweets while categorizing
            logger.info(f"[CURATED_FEED] Creating 'Uncategorized' category for job {job.id}")
            # Use filter().first() instead of get_or_create to avoid async context issues
            uncategorized_category = TweetCategory.objects.filter(
                curated_feed=curated_feed,
                name='Uncategorized'
            ).first()
            if not uncategorized_category:
                uncategorized_category = TweetCategory.objects.create(
                    curated_feed=curated_feed,
                    name='Uncategorized',
                    description='Tweets being categorized...',
                    summary='These tweets are being processed and will be moved to appropriate categories shortly.'
                )
            
            for idx, tweet_data in enumerate(tweets_data, 1):
                if idx % 10 == 0 or idx == len(tweets_data):
                    logger.info(f"[CURATED_FEED] Storing tweet {idx}/{len(tweets_data)} for job {job.id}")
                
                # Parse timestamp
                created_at = bookmark_service._parse_timestamp(tweet_data.get('created_at'))
                
                # Get or create tweet (use filter().first() to avoid async context issues)
                tweet = Tweet.objects.filter(tweet_id=tweet_data['tweet_id']).first()
                created = False
                if not tweet:
                    tweet = Tweet.objects.create(
                        tweet_id=tweet_data['tweet_id'],
                        twitter_profile=twitter_profile,
                        author_username=tweet_data.get('author_username', ''),
                        author_display_name=tweet_data.get('author_display_name', ''),
                        author_profile_image_url=tweet_data.get('author_profile_image_url', ''),
                        text_content=tweet_data.get('text_content', ''),
                        created_at=created_at,
                        like_count=tweet_data.get('like_count', 0),
                        retweet_count=tweet_data.get('retweet_count', 0),
                        reply_count=tweet_data.get('reply_count', 0),
                        is_bookmark=False,  # These are not bookmarks
                        raw_data=tweet_data,
                    )
                    created = True
                else:
                    # Update existing tweet's processing_date
                    tweet.processing_date = job.processing_date
                    tweet.save(update_fields=['processing_date'])
                
                # Immediately add to uncategorized category so it shows up in UI
                if not CategorizedTweet.objects.filter(category=uncategorized_category, tweet=tweet).exists():
                    CategorizedTweet.objects.create(
                        category=uncategorized_category,
                        tweet=tweet
                    )
                
                stored_tweets.append(tweet)
                
                # Update curated feed count incrementally
                curated_feed.num_tweets_fetched = len(stored_tweets)
                try:
                    curated_feed.save(update_fields=['num_tweets_fetched'])
                except Exception as save_error:
                    # If save fails due to async context, log and continue
                    logger.warning(f"[CURATED_FEED] Could not save curated feed progress: {save_error}")
                
                # Update job progress incrementally (every 10 tweets)
                # Note: We're in sync context after closing fetcher, so save is safe
                if len(stored_tweets) % 10 == 0:
                    job.items_processed = len(stored_tweets)
                    try:
                        job.save(update_fields=['items_processed'])
                    except Exception as save_error:
                        # If save fails due to async context, log and continue
                        logger.warning(f"[CURATED_FEED] Could not save job progress: {save_error}")
            
            logger.info(f"[CURATED_FEED] Stored {len(stored_tweets)} tweets, starting AI categorization for job {job.id}")
            
            # Now categorize tweets incrementally
            categorization_service = TweetCategorizationService(provider=self.ai_provider)
            tweet_dicts = [
                {
                    'tweet_id': t.tweet_id,
                    'text_content': t.text_content,
                    'author_username': t.author_username,
                }
                for t in stored_tweets
            ]
            
            categorized_tweets = categorization_service.categorize_tweets(tweet_dicts)
            
            logger.info(f"[CURATED_FEED] AI categorization complete: {len(categorized_tweets)} categories for job {job.id}")
            
            # Store categories and move tweets from uncategorized to their categories
            num_categories = 0
            tweets_to_remove_from_uncategorized = []
            
            for category_name, category_tweets in categorized_tweets.items():
                # Skip "Uncategorized" if it appears (shouldn't happen, but just in case)
                if category_name.lower() == 'uncategorized':
                    continue
                
                tweet_count = len(category_tweets.get('tweets', [])) if isinstance(category_tweets, dict) else len(category_tweets) if isinstance(category_tweets, list) else 0
                logger.info(f"[CURATED_FEED] Creating category '{category_name}' with {tweet_count} tweets for job {job.id}")
                
                # Create category (use filter().first() to avoid async context issues)
                category = TweetCategory.objects.filter(
                    curated_feed=curated_feed,
                    name=category_name
                ).first()
                if not category:
                    category = TweetCategory.objects.create(
                        curated_feed=curated_feed,
                        name=category_name,
                        description=f"Category: {category_name}",
                        summary=''  # Could be enhanced with AI summary
                    )
                num_categories += 1
                
                # Link tweets to category and remove from uncategorized
                category_tweet_list = category_tweets.get('tweets', []) if isinstance(category_tweets, dict) else category_tweets if isinstance(category_tweets, list) else []
                for tweet_dict in category_tweet_list:
                    tweet_id = tweet_dict.get('tweet_id') if isinstance(tweet_dict, dict) else tweet_dict
                    if tweet_id:
                        try:
                            tweet = Tweet.objects.get(tweet_id=tweet_id)
                            # Add to new category
                            if not CategorizedTweet.objects.filter(category=category, tweet=tweet).exists():
                                CategorizedTweet.objects.create(
                                    category=category,
                                    tweet=tweet
                                )
                            # Mark for removal from uncategorized
                            tweets_to_remove_from_uncategorized.append(tweet)
                        except Tweet.DoesNotExist:
                            continue
            
            # Remove tweets from uncategorized category (they're now in proper categories)
            if tweets_to_remove_from_uncategorized:
                CategorizedTweet.objects.filter(
                    category=uncategorized_category,
                    tweet__in=tweets_to_remove_from_uncategorized
                ).delete()
            
            # If all tweets are categorized, delete the uncategorized category
            remaining_uncategorized = CategorizedTweet.objects.filter(category=uncategorized_category).count()
            if remaining_uncategorized == 0:
                uncategorized_category.delete()
            
            # Update curated feed with category count
            curated_feed.num_categories = num_categories
            try:
                curated_feed.save(update_fields=['num_categories'])
            except Exception as save_error:
                # If save fails due to async context, log and continue
                logger.warning(f"[CURATED_FEED] Could not save curated feed category count: {save_error}")
            
            logger.info(f"[CURATED_FEED] Job {job.id} completed successfully: {len(stored_tweets)} tweets, {num_categories} categories")
            
            # Don't save job status here - let the task handler save after we return
            # The fetcher is already closed, but to be safe, let the task handler handle it
            # We'll update items_processed in the return value, and the task handler will save
            
            return {
                'items_processed': len(stored_tweets),
                'success': True,
                'metadata': {
                    'total_fetched': len(tweets_data),
                    'categories_created': num_categories
                }
            }
            
        except FetcherError as e:
            # Handle fetcher errors
            error_msg = str(e)
            logger.error(f"[CURATED_FEED] Fetcher error for job {job.id}: {error_msg}")
            
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
            
            # Let the task handler save the job status - just raise the exception
            if isinstance(e, CredentialError):
                raise CredentialError(error_msg, job=job) from e
            else:
                raise ProcessingError(error_msg, retryable=True, job=job) from e
                
        except Exception as e:
            # Handle other errors
            import traceback
            error_msg = str(e)
            error_traceback = traceback.format_exc()
            
            logger.error(f"[CURATED_FEED] Unexpected error for job {job.id}: {error_msg}", exc_info=True)
            
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
            
            # Let the task handler save the job status - just raise the exception
            raise ProcessingError(error_msg, retryable=True, job=job) from e
            
        finally:
            # Always close fetcher
            if fetcher:
                try:
                    fetcher.close()
                except Exception:
                    pass

