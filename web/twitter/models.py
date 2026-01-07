from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
from django.conf import settings
import base64
import os


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

