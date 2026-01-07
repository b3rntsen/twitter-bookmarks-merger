from django.contrib import admin
from .models import CuratedFeed, TweetCategory, CategorizedTweet


@admin.register(CuratedFeed)
class CuratedFeedAdmin(admin.ModelAdmin):
    list_display = ['user', 'twitter_profile', 'created_at', 'num_tweets_fetched', 'num_categories', 'config_num_tweets']
    list_filter = ['created_at', 'num_categories']
    search_fields = ['user__email', 'user__username']
    readonly_fields = ['created_at']


@admin.register(TweetCategory)
class TweetCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'curated_feed', 'created_at']
    list_filter = ['curated_feed', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']


@admin.register(CategorizedTweet)
class CategorizedTweetAdmin(admin.ModelAdmin):
    list_display = ['category', 'tweet', 'created_at']
    list_filter = ['category', 'created_at']
    search_fields = ['category__name', 'tweet__text_content', 'tweet__author_username']
    readonly_fields = ['created_at']

