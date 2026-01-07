"""
Models for content processing and job management.
"""
from django.db import models
from django.contrib.auth.models import User
from datetime import time


class ContentProcessingJob(models.Model):
    """Tracks a single content processing job for a user."""
    
    CONTENT_TYPE_CHOICES = [
        ('bookmarks', 'Bookmarks'),
        ('curated_feed', 'Curated Feed'),
        ('lists', 'Lists'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
    ]
    
    # Relationships
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='processing_jobs')
    twitter_profile = models.ForeignKey('twitter.TwitterProfile', on_delete=models.CASCADE, related_name='processing_jobs')
    
    # Job identification
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES)
    processing_date = models.DateField(db_index=True, help_text="Date for which content is being processed")
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    retry_count = models.IntegerField(default=0, help_text="Number of retry attempts")
    max_retries = models.IntegerField(default=5, help_text="Maximum retry attempts")
    
    # Timing
    scheduled_at = models.DateTimeField(help_text="When the job was scheduled to run")
    started_at = models.DateTimeField(null=True, blank=True, help_text="When the job started processing")
    completed_at = models.DateTimeField(null=True, blank=True, help_text="When the job completed")
    next_retry_at = models.DateTimeField(null=True, blank=True, help_text="When to retry if failed")
    
    # Results
    items_processed = models.IntegerField(default=0, help_text="Number of items (tweets, etc.) processed")
    error_message = models.TextField(blank=True, help_text="Error message if job failed")
    error_traceback = models.TextField(blank=True, help_text="Full traceback if job failed")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-processing_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'processing_date', 'content_type']),
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['twitter_profile', 'content_type', 'processing_date']),
        ]
        unique_together = ['user', 'twitter_profile', 'content_type', 'processing_date']
    
    def get_tweets_saved_count(self) -> int:
        """
        Get the actual number of tweets saved to the database by this job.
        This counts tweets regardless of job status (running, completed, failed).
        
        Returns:
            int: Number of tweets saved
        """
        from twitter.models import Tweet
        from lists_app.models import ListTweet
        from bookmarks_app.models import CuratedFeed, CategorizedTweet
        
        if self.content_type == 'bookmarks':
            # Count bookmarks with this processing_date
            return Tweet.objects.filter(
                twitter_profile=self.twitter_profile,
                is_bookmark=True,
                processing_date=self.processing_date
            ).count()
        
        elif self.content_type == 'curated_feed':
            # Count tweets in CuratedFeed(s) for this processing_date
            # Handle case where multiple CuratedFeeds exist (e.g., from testing)
            curated_feeds = CuratedFeed.objects.filter(
                user=self.user,
                twitter_profile=self.twitter_profile,
                processing_date=self.processing_date
            )
            
            if curated_feeds.exists():
                # Sum up tweets from all CuratedFeeds for this date
                return CategorizedTweet.objects.filter(
                    category__curated_feed__in=curated_feeds
                ).count()
            else:
                # Fallback: count tweets with this processing_date that aren't bookmarks
                return Tweet.objects.filter(
                    twitter_profile=self.twitter_profile,
                    is_bookmark=False,
                    processing_date=self.processing_date
                ).exclude(
                    # Exclude tweets that are only bookmarks
                    id__in=Tweet.objects.filter(
                        twitter_profile=self.twitter_profile,
                        is_bookmark=True,
                        processing_date=self.processing_date
                    ).values_list('id', flat=True)
                ).count()
        
        elif self.content_type == 'lists':
            # Count ListTweets with this seen_date (which equals processing_date)
            return ListTweet.objects.filter(
                twitter_list__twitter_profile=self.twitter_profile,
                seen_date=self.processing_date
            ).count()
        
        return 0
    
    def __str__(self):
        return f"{self.user.username} - {self.content_type} - {self.processing_date} ({self.status})"


class ProcessingSchedule(models.Model):
    """User-specific processing schedule configuration."""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='processing_schedule')
    
    # Schedule configuration
    processing_time = models.TimeField(default=time(2, 0), help_text="UTC time for daily processing")
    timezone = models.CharField(max_length=50, default='UTC', help_text="User's timezone (for display)")
    enabled = models.BooleanField(default=True, help_text="Whether automatic processing is enabled")
    
    # Content type preferences
    process_bookmarks = models.BooleanField(default=True)
    process_curated_feed = models.BooleanField(default=True)
    process_lists = models.BooleanField(default=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['user']
    
    def __str__(self):
        return f"Schedule for {self.user.username} - {self.processing_time} UTC"


class DailyContentSnapshot(models.Model):
    """Snapshot of processed content for a user on a specific date."""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_snapshots')
    twitter_profile = models.ForeignKey('twitter.TwitterProfile', on_delete=models.CASCADE, related_name='daily_snapshots')
    processing_date = models.DateField(db_index=True)
    
    # Content counts
    bookmark_count = models.IntegerField(default=0)
    curated_feed_count = models.IntegerField(default=0)
    list_count = models.IntegerField(default=0)
    total_tweet_count = models.IntegerField(default=0)
    
    # Processing status
    all_jobs_completed = models.BooleanField(default=False, help_text="True if all content types processed successfully")
    last_processed_at = models.DateTimeField(null=True, blank=True, help_text="When last job completed")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-processing_date']
        indexes = [
            models.Index(fields=['user', 'processing_date']),
            models.Index(fields=['twitter_profile', 'processing_date']),
        ]
        unique_together = ['user', 'twitter_profile', 'processing_date']
    
    def __str__(self):
        return f"Snapshot for {self.user.username} - {self.processing_date}"
