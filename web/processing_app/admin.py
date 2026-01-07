from django.contrib import admin
from .models import ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot


@admin.register(ContentProcessingJob)
class ContentProcessingJobAdmin(admin.ModelAdmin):
    """Admin interface for ContentProcessingJob."""
    list_display = ['user', 'twitter_profile', 'content_type', 'processing_date', 'status', 
                    'retry_count', 'items_processed', 'scheduled_at', 'started_at', 'completed_at']
    list_filter = ['status', 'content_type', 'processing_date', 'created_at']
    search_fields = ['user__email', 'user__username', 'twitter_profile__twitter_username']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'processing_date'
    ordering = ['-processing_date', '-created_at']
    
    fieldsets = (
        ('Job Information', {
            'fields': ('user', 'twitter_profile', 'content_type', 'processing_date')
        }),
        ('Status', {
            'fields': ('status', 'retry_count', 'max_retries', 'next_retry_at')
        }),
        ('Timing', {
            'fields': ('scheduled_at', 'started_at', 'completed_at')
        }),
        ('Results', {
            'fields': ('items_processed', 'error_message', 'error_traceback')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ProcessingSchedule)
class ProcessingScheduleAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingSchedule."""
    list_display = ['user', 'processing_time', 'timezone', 'enabled', 
                    'process_bookmarks', 'process_curated_feed', 'process_lists', 'updated_at']
    list_filter = ['enabled', 'process_bookmarks', 'process_curated_feed', 'process_lists']
    search_fields = ['user__email', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['user']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Schedule Configuration', {
            'fields': ('processing_time', 'timezone', 'enabled')
        }),
        ('Content Type Preferences', {
            'fields': ('process_bookmarks', 'process_curated_feed', 'process_lists')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DailyContentSnapshot)
class DailyContentSnapshotAdmin(admin.ModelAdmin):
    """Admin interface for DailyContentSnapshot."""
    list_display = ['user', 'twitter_profile', 'processing_date', 'bookmark_count', 
                    'curated_feed_count', 'list_count', 'total_tweet_count', 
                    'all_jobs_completed', 'last_processed_at']
    list_filter = ['all_jobs_completed', 'processing_date', 'created_at']
    search_fields = ['user__email', 'user__username', 'twitter_profile__twitter_username']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'processing_date'
    ordering = ['-processing_date']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'twitter_profile', 'processing_date')
        }),
        ('Content Counts', {
            'fields': ('bookmark_count', 'curated_feed_count', 'list_count', 'total_tweet_count')
        }),
        ('Processing Status', {
            'fields': ('all_jobs_completed', 'last_processed_at')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
