"""
Models for curated feed functionality.
"""
from django.db import models
from django.contrib.auth.models import User
from twitter.models import TwitterProfile, Tweet


class CuratedFeed(models.Model):
    """Stores metadata about a curated feed fetch."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='curated_feeds')
    twitter_profile = models.ForeignKey(TwitterProfile, on_delete=models.CASCADE, related_name='curated_feeds')
    created_at = models.DateTimeField(auto_now_add=True)
    num_tweets_fetched = models.IntegerField(default=0)
    num_categories = models.IntegerField(default=0)
    config_num_tweets = models.IntegerField(default=100, help_text="Configured number of tweets to fetch")
    
    # Processing metadata
    processing_date = models.DateField(null=True, blank=True, db_index=True, 
                                      help_text="Date when this curated feed was processed/fetched")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['processing_date']),
        ]
    
    def __str__(self):
        return f"Curated Feed for {self.user.username} - {self.created_at}"


class TweetCategory(models.Model):
    """Represents a category of tweets."""
    curated_feed = models.ForeignKey(CuratedFeed, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    summary = models.TextField(blank=True, help_text="AI-generated summary of tweets in this category")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        unique_together = ['curated_feed', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.curated_feed})"


class CategorizedTweet(models.Model):
    """Links tweets to categories in a curated feed."""
    category = models.ForeignKey(TweetCategory, on_delete=models.CASCADE, related_name='tweets')
    tweet = models.ForeignKey(Tweet, on_delete=models.CASCADE, related_name='categorized_in')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-tweet__created_at']
        unique_together = ['category', 'tweet']
    
    def __str__(self):
        return f"{self.category.name} - {self.tweet}"
