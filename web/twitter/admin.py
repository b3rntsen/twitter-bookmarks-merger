from django.contrib import admin
from .models import TwitterProfile, Tweet, TweetThread, TweetMedia, TweetReply


@admin.register(TwitterProfile)
class TwitterProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'twitter_username', 'last_sync_at', 'sync_status')
    list_filter = ('sync_status', 'created_at')
    search_fields = ('user__email', 'twitter_username')


@admin.register(Tweet)
class TweetAdmin(admin.ModelAdmin):
    list_display = ('tweet_id', 'author_username', 'created_at', 'is_bookmark', 'like_count')
    list_filter = ('is_bookmark', 'is_reply', 'created_at')
    search_fields = ('tweet_id', 'author_username', 'text_content')
    readonly_fields = ('scraped_at', 'updated_at')


@admin.register(TweetMedia)
class TweetMediaAdmin(admin.ModelAdmin):
    list_display = ('tweet', 'media_type', 'file_path')
    list_filter = ('media_type', 'created_at')


@admin.register(TweetThread)
class TweetThreadAdmin(admin.ModelAdmin):
    list_display = ('parent_tweet', 'child_tweet', 'thread_order')


@admin.register(TweetReply)
class TweetReplyAdmin(admin.ModelAdmin):
    list_display = ('original_tweet', 'reply_tweet', 'reply_author_username')

