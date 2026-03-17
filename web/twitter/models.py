from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from cryptography.fernet import Fernet
from django.conf import settings
import base64
import os
import logging

logger = logging.getLogger(__name__)


def get_encryption_key():
    """Get encryption key from environment or generate a default for development."""
    from decouple import config
    key = config('ENCRYPTION_KEY', default='')
    if not key:
        # Generate a key for development (should be set in production)
        key = Fernet.generate_key().decode()
    elif len(key) < 32:
        # Pad or hash the key to 32 bytes
        key = key.ljust(32, '0')[:32]
    # Ensure it's base64 encoded
    try:
        base64.urlsafe_b64decode(key)
    except:
        key = base64.urlsafe_b64encode(key.encode()[:32]).decode()
    return key


class TwitterProfile(models.Model):
    """Store Twitter account connection with encrypted credentials."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='twitter_profiles')
    twitter_username = models.CharField(max_length=100)
    twitter_user_id = models.CharField(max_length=100, blank=True)
    
    # Encrypted credentials - can store username/password or session cookies
    encrypted_credentials = models.TextField(help_text="Encrypted Twitter credentials")
    
    # Sync information
    last_sync_at = models.DateTimeField(null=True, blank=True)
    sync_status = models.CharField(
        max_length=20,
        choices=[
            ('success', 'Success'),
            ('error', 'Error'),
            ('pending', 'Pending'),
        ],
        default='pending'
    )
    sync_error_message = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_credentials(self, username, password=None, cookies=None):
        """Encrypt and store Twitter credentials."""
        import json
        data = {
            'username': username,
            'password': password,
            'cookies': cookies,
        }
        json_data = json.dumps(data)
        key = get_encryption_key()
        f = Fernet(key.encode() if isinstance(key, str) else key)
        self.encrypted_credentials = f.encrypt(json_data.encode()).decode()

    def get_credentials(self):
        """Decrypt and retrieve Twitter credentials."""
        if not self.encrypted_credentials:
            return None
        try:
            import json
            key = get_encryption_key()
            f = Fernet(key.encode() if isinstance(key, str) else key)
            decrypted = f.decrypt(self.encrypted_credentials.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            return None

    def __str__(self):
        return f"{self.user.email} - @{self.twitter_username}"


class BookmarkSyncSchedule(models.Model):
    """Configuration for automated bookmark syncing."""
    twitter_profile = models.OneToOneField(
        TwitterProfile,
        on_delete=models.CASCADE,
        related_name='sync_schedule'
    )

    # Schedule configuration
    enabled = models.BooleanField(default=True)
    interval_minutes = models.IntegerField(
        default=60,
        help_text="Base interval between syncs (minutes)"
    )
    randomize_minutes = models.IntegerField(
        default=15,
        help_text="Random variation to add (±minutes)"
    )

    # Active hours (user's local timezone)
    timezone = models.CharField(max_length=50, default='Europe/Copenhagen')
    start_hour = models.IntegerField(
        default=8,
        help_text="Start hour (0-23)",
        validators=[MinValueValidator(0), MaxValueValidator(23)]
    )
    end_hour = models.IntegerField(
        default=24,
        help_text="End hour (1-24, where 24 = end of day)",
        validators=[MinValueValidator(1), MaxValueValidator(24)]
    )

    # Fetch configuration
    max_pages = models.IntegerField(default=2, help_text="Pages to fetch (~40 bookmarks per page)")
    use_until_synced = models.BooleanField(
        default=False,
        help_text="Use gap-free sync mode (rebuild)"
    )

    # Status tracking
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.IntegerField(default=0)
    backoff_multiplier = models.IntegerField(default=1, help_text="Multiplier for interval on transient failures (1-12)")
    last_error_type = models.CharField(max_length=50, blank=True, help_text="Type of last error (e.g. cookie_expired, timeout)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bookmark Sync Schedule"
        verbose_name_plural = "Bookmark Sync Schedules"

    def __str__(self):
        return f"Sync Schedule for {self.twitter_profile.twitter_username}"

    MAX_CONSECUTIVE_FAILURES = 5

    def clean(self):
        """Validate active hours."""
        super().clean()
        if self.start_hour < 0 or self.start_hour > 23:
            raise ValidationError({'start_hour': 'Must be between 0 and 23'})
        if self.end_hour < 1 or self.end_hour > 24:
            raise ValidationError({'end_hour': 'Must be between 1 and 24'})
        if self.end_hour != 24 and self.start_hour >= self.end_hour:
            raise ValidationError('start_hour must be less than end_hour')

    def should_disable_due_to_failures(self):
        """Check if schedule should be disabled due to too many failures."""
        return self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES

    def disable_due_to_failures(self):
        """Disable schedule due to excessive failures."""
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.enabled = False
            self.save()
            logger.warning(
                f"Disabled sync schedule for {self.twitter_profile.twitter_username} "
                f"after {self.consecutive_failures} consecutive failures"
            )
            return True
        return False

    def calculate_next_sync(self):
        """Calculate next sync time with randomization and active hours."""
        import random
        from datetime import datetime, time as dt_time, timedelta
        import pytz

        # Validate timezone with fallback
        try:
            tz = pytz.timezone(self.timezone)
        except pytz.UnknownTimeZoneError:
            logger.error(f"Invalid timezone '{self.timezone}', falling back to UTC")
            tz = pytz.UTC

        now = datetime.now(tz)

        # Add base interval (with backoff) + randomization
        effective_interval = self.interval_minutes * self.backoff_multiplier
        random_offset = random.randint(-self.randomize_minutes, self.randomize_minutes)
        next_time = now + timedelta(minutes=effective_interval + random_offset)

        # Normalize end_hour: 24 means "end of day" (no upper bound)
        effective_end_hour = 24 if self.end_hour == 24 else self.end_hour

        # If outside active hours, move to next start_hour
        if next_time.hour < self.start_hour:
            # Before start hour - move to today's start_hour
            next_time = tz.localize(
                datetime.combine(next_time.date(), dt_time(self.start_hour, 0, 0))
            )
        elif effective_end_hour != 24 and next_time.hour >= effective_end_hour:
            # After end hour - move to tomorrow's start_hour
            tomorrow = next_time.date() + timedelta(days=1)
            next_time = tz.localize(
                datetime.combine(tomorrow, dt_time(self.start_hour, 0, 0))
            )

        # Ensure next_time is in the future
        if next_time <= now:
            next_time = now + timedelta(minutes=self.interval_minutes)

        return next_time.astimezone(pytz.UTC)


class BookmarkSyncJob(models.Model):
    """Track bookmark sync job execution."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    twitter_profile = models.ForeignKey(
        TwitterProfile,
        on_delete=models.CASCADE,
        related_name='sync_jobs'
    )

    # Timing
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # Results
    bookmarks_fetched = models.IntegerField(default=0)
    pages_fetched = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    error_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g., 'cookie_expired', 'rate_limit', 'network_error'"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_at']
        indexes = [
            models.Index(fields=['twitter_profile', '-scheduled_at']),
            models.Index(fields=['status', 'scheduled_at']),
        ]

    def __str__(self):
        return f"Sync Job #{self.id} - {self.twitter_profile.twitter_username} ({self.status})"


class Tweet(models.Model):
    """Individual tweet storage."""
    twitter_profile = models.ForeignKey(TwitterProfile, on_delete=models.CASCADE, related_name='tweets')
    tweet_id = models.CharField(max_length=100, unique=True, db_index=True)
    author_username = models.CharField(max_length=100)
    author_display_name = models.CharField(max_length=200, blank=True, help_text="Display name (e.g., 'Dave Shapiro')")
    author_profile_image_url = models.URLField(max_length=500, blank=True, help_text="Profile picture URL")
    author_id = models.CharField(max_length=100, blank=True)
    text_content = models.TextField()
    html_content = models.TextField(blank=True, help_text="Original HTML from x.com")
    html_content_sanitized = models.TextField(blank=True, help_text="Sanitized HTML with local URLs and no JavaScript")
    created_at = models.DateTimeField()
    
    # Engagement metrics
    like_count = models.IntegerField(default=0)
    retweet_count = models.IntegerField(default=0)
    reply_count = models.IntegerField(default=0)
    
    # Threading
    is_bookmark = models.BooleanField(default=True)
    is_reply = models.BooleanField(default=False)
    in_reply_to_tweet_id = models.CharField(max_length=100, blank=True, null=True)
    conversation_id = models.CharField(max_length=100, blank=True)
    thread_position = models.IntegerField(default=0)
    
    # Metadata
    raw_data = models.JSONField(default=dict, blank=True)
    scraped_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Processing metadata
    processing_date = models.DateField(null=True, blank=True, db_index=True, 
                                      help_text="Date when this tweet was processed/fetched")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tweet_id']),
            models.Index(fields=['conversation_id']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['processing_date']),
        ]

    def __str__(self):
        return f"@{self.author_username}: {self.text_content[:50]}..."


class TweetThread(models.Model):
    """Thread relationships between tweets."""
    parent_tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='child_threads')
    child_tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='parent_threads')
    thread_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['parent_tweet', 'child_tweet']
        ordering = ['thread_order']

    def __str__(self):
        return f"Thread: {self.parent_tweet.tweet_id} -> {self.child_tweet.tweet_id}"


class TweetMedia(models.Model):
    """Media attachments for tweets."""
    MEDIA_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('gif', 'GIF'),
    ]
    
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='media')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES)
    file_path = models.CharField(max_length=500)
    original_url = models.URLField(max_length=1000)
    thumbnail_path = models.CharField(max_length=500, blank=True)
    file_size = models.IntegerField(default=0, help_text="File size in bytes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.media_type} for {self.tweet.tweet_id}"


class TweetReply(models.Model):
    """Replies to tweets for thread context."""
    original_tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='replies')
    reply_tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='reply_to')
    reply_author_username = models.CharField(max_length=100)
    reply_author_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['original_tweet', 'reply_tweet']
        ordering = ['created_at']

    def __str__(self):
        return f"Reply to {self.original_tweet.tweet_id} by @{self.reply_author_username}"

