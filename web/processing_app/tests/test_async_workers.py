"""
Integration tests for async workers with real execution (not mocked).

These tests execute actual async workers to identify and debug real-world failures.
Tests limit fetches to 10 items per type to avoid rate limiting and ensure fast execution.

NOTE: These tests use real credentials from the database (first user's TwitterProfile).
The tests automatically:
1. Load credentials from the first user in the database
2. Use cookies from twitter_auth file for cookie-based authentication (to work around bot detection)
3. Fall back to test credentials if no real credentials are found

The tests verify that:
1. Debug output shows progress at each step
2. Errors are properly logged and captured
3. Job status is correctly updated (completed or failed)
4. Error messages provide context about what failed

To ensure tests use real credentials:
  - Have at least one user with a TwitterProfile in the database
  - Ensure the TwitterProfile has valid credentials set
  - Or ensure twitter_auth file exists with valid cookies
"""
import pytest
import logging
from datetime import date
from django.utils import timezone
from processing_app.models import ContentProcessingJob
from processing_app.tasks import process_content_job
from twitter.models import Tweet
from lists_app.models import TwitterList, ListTweet, Event


@pytest.mark.django_db
class TestAsyncWorkers:
    """Integration tests for async workers with real execution."""
    
    def test_lists_to_tweets(self, user, twitter_profile, twitter_list, monkeypatch, caplog):
        """
        Test lists-to-tweets async worker with clean database and debug output.
        
        This test executes the real async worker (not mocked) to identify failures
        in lists-to-tweets processing. It limits fetches to 10 tweets per list to
        avoid rate limiting.
        """
        # Set environment variable to limit fetches
        monkeypatch.setenv('LIST_MAX_TWEETS', '10')
        
        # Configure logging to capture debug output
        with caplog.at_level(logging.INFO, logger='processing_app'):
            # Create job for lists processing
            job = ContentProcessingJob.objects.create(
                user=user,
                twitter_profile=twitter_profile,
                content_type='lists',
                processing_date=date.today(),
                status='pending',
                scheduled_at=timezone.now(),
            )
            
            # Execute the async worker
            process_content_job(job.id)
            
            # Refresh job from database
            job.refresh_from_db()
            
            # Verify job status
            assert job.status in ['completed', 'failed'], f"Job status should be completed or failed, got {job.status}"
            
            if job.status == 'completed':
                # Verify items were processed
                assert job.items_processed >= 0, "items_processed should be non-negative"
                
                # Verify tweets were stored with correct processing_date
                tweets = Tweet.objects.filter(
                    twitter_profile=twitter_profile,
                    processing_date=job.processing_date
                )
                assert tweets.count() == job.items_processed, \
                    f"Tweet count ({tweets.count()}) should match items_processed ({job.items_processed})"
                
                # Verify ListTweet objects link tweets to lists
                list_tweets = ListTweet.objects.filter(twitter_list=twitter_list)
                if job.items_processed > 0:
                    assert list_tweets.count() > 0, "ListTweet objects should be created when tweets are processed"
                    # Verify seen_date matches processing_date
                    for list_tweet in list_tweets:
                        assert list_tweet.seen_date == job.processing_date, \
                            f"ListTweet seen_date should match processing_date"
                
                # Verify events were generated from list tweets
                events = Event.objects.filter(twitter_list=twitter_list)
                # Events may or may not be created depending on tweet content and grouping
                # This is informational, not a hard requirement
                if events.exists():
                    assert all(event.tweet_count > 0 for event in events), \
                        "Events should have tweet_count > 0"
            else:
                # Job failed - verify error message is present
                assert job.error_message is not None, "Failed job should have error_message"
                assert len(job.error_message) > 0, "error_message should not be empty"
            
            # Verify debug output shows progress
            log_text = caplog.text
            assert "[LISTS]" in log_text or "[TASK]" in log_text, \
                "Debug output should contain [LISTS] or [TASK] log messages"
            
            # Check for key progress indicators
            progress_indicators = [
                "Starting job",
                "Fetching",
                "Processing",
            ]
            found_indicators = [ind for ind in progress_indicators if ind.lower() in log_text.lower()]
            assert len(found_indicators) > 0, \
                f"Debug output should show progress. Found: {found_indicators}, Log: {log_text[:500]}"
            
            # If job failed, verify error context is in logs
            if job.status == 'failed':
                assert "error" in log_text.lower() or "failed" in log_text.lower(), \
                    "Failed job should have error messages in debug output"
                
                # Log a summary of the failure for easier debugging
                print(f"\n[TEST DEBUG] Bookmarks job failed with error: {job.error_message}")
                print(f"[TEST DEBUG] Error occurred during: {log_text[:200]}...")
                
                # Log a summary of the failure for easier debugging
                print(f"\n[TEST DEBUG] Lists-to-tweets job failed with error: {job.error_message}")
                print(f"[TEST DEBUG] Error occurred during: {log_text[:200]}...")
    
    def test_bookmarks(self, user, twitter_profile, monkeypatch, caplog):
        """
        Test bookmarks async worker with clean database and debug output.
        
        This test executes the real async worker (not mocked) to identify failures
        in bookmarks processing. It limits fetches to 10 bookmarks to avoid rate limiting.
        """
        # Set environment variable to limit fetches
        monkeypatch.setenv('BOOKMARK_MAX_ITEMS', '10')
        
        # Configure logging to capture debug output
        with caplog.at_level(logging.INFO, logger='processing_app'):
            # Create job for bookmarks processing
            job = ContentProcessingJob.objects.create(
                user=user,
                twitter_profile=twitter_profile,
                content_type='bookmarks',
                processing_date=date.today(),
                status='pending',
                scheduled_at=timezone.now(),
            )
            
            # Execute the async worker
            process_content_job(job.id)
            
            # Refresh job from database
            job.refresh_from_db()
            
            # Verify job status
            assert job.status in ['completed', 'failed'], f"Job status should be completed or failed, got {job.status}"
            
            if job.status == 'completed':
                # Verify items were processed
                assert job.items_processed >= 0, "items_processed should be non-negative"
                
                # Verify bookmarks (tweets) were stored with correct processing_date
                tweets = Tweet.objects.filter(
                    twitter_profile=twitter_profile,
                    processing_date=job.processing_date,
                    is_bookmark=True
                )
                assert tweets.count() == job.items_processed, \
                    f"Bookmark count ({tweets.count()}) should match items_processed ({job.items_processed})"
                
                # Verify processing_date is set correctly
                for tweet in tweets:
                    assert tweet.processing_date == job.processing_date, \
                        f"Tweet processing_date should match job processing_date"
                    assert tweet.is_bookmark is True, "Bookmark tweets should have is_bookmark=True"
            else:
                # Job failed - verify error message is present
                assert job.error_message is not None, "Failed job should have error_message"
                assert len(job.error_message) > 0, "error_message should not be empty"
            
            # Verify debug output shows progress
            log_text = caplog.text
            assert "[BOOKMARKS]" in log_text or "[TASK]" in log_text, \
                "Debug output should contain [BOOKMARKS] or [TASK] log messages"
            
            # Check for key progress indicators
            progress_indicators = [
                "Starting job",
                "Fetching",
                "Storing",
            ]
            found_indicators = [ind for ind in progress_indicators if ind.lower() in log_text.lower()]
            assert len(found_indicators) > 0, \
                f"Debug output should show progress. Found: {found_indicators}, Log: {log_text[:500]}"
            
            # If job failed, verify error context is in logs
            if job.status == 'failed':
                assert "error" in log_text.lower() or "failed" in log_text.lower(), \
                    "Failed job should have error messages in debug output"
                
                # Log a summary of the failure for easier debugging
                print(f"\n[TEST DEBUG] Bookmarks job failed with error: {job.error_message}")
                print(f"[TEST DEBUG] Error occurred during: {log_text[:200]}...")

