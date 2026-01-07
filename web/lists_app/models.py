from django.db import models
from django.contrib.auth.models import User
from twitter.models import TwitterProfile, Tweet


class TwitterList(models.Model):
    """A Twitter list that the user follows."""
    twitter_profile = models.ForeignKey(TwitterProfile, on_delete=models.CASCADE, related_name='twitter_lists')
    list_id = models.CharField(max_length=100, unique=True, db_index=True)
    list_name = models.CharField(max_length=200)
    list_slug = models.CharField(max_length=200, blank=True)
    list_url = models.URLField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    member_count = models.IntegerField(default=0)
    subscriber_count = models.IntegerField(default=0)
    
    # Metadata
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['list_name']
        unique_together = ['twitter_profile', 'list_id']
    
    def __str__(self):
        return f"{self.list_name} (@{self.twitter_profile.twitter_username})"


class ListTweet(models.Model):
    """Tweets from a specific Twitter list."""
    twitter_list = models.ForeignKey(TwitterList, on_delete=models.CASCADE, related_name='tweets')
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='list_tweets')
    
    # Store the date this tweet was seen in the list (for daily summaries)
    seen_date = models.DateField(db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-seen_date', '-tweet__created_at']
        unique_together = ['twitter_list', 'tweet', 'seen_date']
        indexes = [
            models.Index(fields=['twitter_list', 'seen_date']),
        ]
    
    def __str__(self):
        return f"{self.twitter_list.list_name} - {self.tweet.tweet_id} ({self.seen_date})"


class Event(models.Model):
    """A grouped event representing multiple tweets about the same topic."""
    twitter_list = models.ForeignKey(TwitterList, on_delete=models.CASCADE, related_name='events')
    event_date = models.DateField(db_index=True)
    
    # Event identification
    headline = models.CharField(max_length=500, help_text="Generated headline for the event")
    summary = models.TextField(help_text="AI-generated summary of the event from all related tweets")
    
    # Metadata
    tweet_count = models.IntegerField(default=0, help_text="Number of tweets in this event")
    keywords = models.JSONField(default=list, blank=True, help_text="Keywords that identify this event")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-event_date', '-created_at']
        indexes = [
            models.Index(fields=['twitter_list', 'event_date']),
        ]
    
    def __str__(self):
        return f"{self.headline} ({self.event_date})"


class EventTweet(models.Model):
    """Association between an event and a tweet."""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='event_tweets')
    list_tweet = models.ForeignKey(ListTweet, on_delete=models.CASCADE, related_name='events')
    
    # Relevance score (0-1) indicating how relevant this tweet is to the event
    relevance_score = models.FloatField(default=1.0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-relevance_score', '-list_tweet__tweet__created_at']
        unique_together = ['event', 'list_tweet']
    
    def __str__(self):
        return f"{self.event.headline} - {self.list_tweet.tweet.tweet_id}"
