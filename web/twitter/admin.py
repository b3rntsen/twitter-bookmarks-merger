from django.contrib import admin
from django.utils.html import format_html
from .models import TwitterProfile, Tweet, TweetThread, TweetMedia, TweetReply, BookmarkSyncSchedule, BookmarkSyncJob


@admin.register(TwitterProfile)
class TwitterProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'twitter_username', 'last_sync_at', 'sync_status')
    list_filter = ('sync_status', 'created_at')
    search_fields = ('user__email', 'twitter_username')


@admin.register(BookmarkSyncSchedule)
class BookmarkSyncScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'twitter_profile',
        'enabled',
        'interval_display',
        'active_hours_display',
        'next_sync_display',
        'failure_status'
    ]
    list_filter = ['enabled', 'consecutive_failures']
    search_fields = ['twitter_profile__twitter_username']
    actions = ['reset_failures', 'reschedule_now', 'disable_schedules']

    fieldsets = (
        ('Profile', {
            'fields': ('twitter_profile',)
        }),
        ('Schedule', {
            'fields': ('enabled', 'interval_minutes', 'randomize_minutes', 'timezone')
        }),
        ('Active Hours', {
            'fields': ('start_hour', 'end_hour')
        }),
        ('Fetch Settings', {
            'fields': ('max_pages', 'use_until_synced')
        }),
        ('Status', {
            'fields': ('last_scheduled_at', 'next_sync_at', 'consecutive_failures'),
            'classes': ('collapse',)
        }),
    )

    def interval_display(self, obj):
        return f"{obj.interval_minutes} ± {obj.randomize_minutes} min"
    interval_display.short_description = "Interval"

    def active_hours_display(self, obj):
        return f"{obj.start_hour:02d}:00 - {obj.end_hour:02d}:00 {obj.timezone}"
    active_hours_display.short_description = "Active Hours"

    def next_sync_display(self, obj):
        if obj.next_sync_at:
            return obj.next_sync_at.strftime("%Y-%m-%d %H:%M %Z")
        return "Not scheduled"
    next_sync_display.short_description = "Next Sync"

    def failure_status(self, obj):
        if obj.consecutive_failures >= 3:
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠️ {} failures</span>',
                obj.consecutive_failures
            )
        elif obj.consecutive_failures > 0:
            return format_html(
                '<span style="color: orange;">{} failures</span>',
                obj.consecutive_failures
            )
        return format_html('<span style="color: green;">✓ OK</span>')
    failure_status.short_description = "Status"

    def reset_failures(self, request, queryset):
        """Reset consecutive failures counter."""
        count = queryset.update(consecutive_failures=0)
        self.message_user(request, f'Reset failures for {count} schedules')
    reset_failures.short_description = "Reset failure counter"

    def reschedule_now(self, request, queryset):
        """Reschedule selected profiles immediately."""
        from twitter.tasks import schedule_next_bookmark_sync
        success_count = 0
        for schedule in queryset:
            try:
                schedule_next_bookmark_sync(schedule.twitter_profile.id)
                success_count += 1
            except Exception as e:
                self.message_user(request, f'Error rescheduling {schedule}: {e}', level='ERROR')
        self.message_user(request, f'Rescheduled {success_count} schedules')
    reschedule_now.short_description = "Reschedule now"

    def disable_schedules(self, request, queryset):
        """Disable selected schedules."""
        count = queryset.update(enabled=False)
        self.message_user(request, f'Disabled {count} schedules')
    disable_schedules.short_description = "Disable schedules"


@admin.register(BookmarkSyncJob)
class BookmarkSyncJobAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'twitter_profile',
        'scheduled_at',
        'status_display',
        'bookmarks_fetched',
        'duration',
        'error_type',
        'log_preview',
    ]
    list_filter = ['status', 'error_type', 'scheduled_at']
    search_fields = ['twitter_profile__twitter_username', 'error_message']
    readonly_fields = [
        'scheduled_at', 'started_at', 'completed_at',
        'bookmarks_fetched', 'pages_fetched', 'error_type', 'log_display'
    ]
    exclude = ['error_message']  # replaced by log_display
    actions = ['mark_failed_as_pending', 'cancel_pending_jobs']

    fieldsets = (
        ('Job Info', {
            'fields': ('twitter_profile', 'scheduled_at', 'status')
        }),
        ('Timing', {
            'fields': ('started_at', 'completed_at')
        }),
        ('Results', {
            'fields': ('bookmarks_fetched', 'pages_fetched', 'error_type')
        }),
        ('Log Output', {
            'fields': ('log_display',),
        }),
    )

    def status_display(self, obj):
        colors = {
            'pending': 'gray',
            'running': 'blue',
            'success': 'green',
            'failed': 'red'
        }
        return format_html(
            '<span style="color: {};">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_display.short_description = "Status"

    def duration(self, obj):
        if obj.started_at and obj.completed_at:
            delta = obj.completed_at - obj.started_at
            return f"{delta.total_seconds():.1f}s"
        return "-"
    duration.short_description = "Duration"

    def log_preview(self, obj):
        """Truncated log for list view."""
        log = obj.error_message or ''
        if '--- RESULT ---' in log:
            result = log.split('--- RESULT ---')[-1].strip()
            return result[:100]
        return log[-80:] if log else '-'
    log_preview.short_description = "Log"

    def log_display(self, obj):
        """Full log output as formatted HTML."""
        log = obj.error_message or 'No log output'
        return format_html(
            '<pre style="background:#1a1a2e; color:#e0e0e0; padding:12px; '
            'border-radius:8px; max-height:500px; overflow:auto; '
            'font-family:monospace; font-size:12px; white-space:pre-wrap; '
            'word-break:break-word;">{}</pre>',
            log
        )
    log_display.short_description = "Log Output"

    def mark_failed_as_pending(self, request, queryset):
        """Reset failed jobs to pending for retry."""
        from django.utils import timezone
        count = queryset.filter(status='failed').update(
            status='pending',
            error_message='',
            error_type='',
            started_at=None,
            completed_at=None
        )
        self.message_user(request, f'Reset {count} failed jobs to pending')
    mark_failed_as_pending.short_description = "Reset failed jobs to pending"

    def cancel_pending_jobs(self, request, queryset):
        """Cancel pending jobs."""
        from django.utils import timezone
        count = queryset.filter(status='pending').update(
            status='failed',
            error_message='Canceled by admin',
            error_type='canceled',
            completed_at=timezone.now()
        )
        self.message_user(request, f'Canceled {count} pending jobs')
    cancel_pending_jobs.short_description = "Cancel pending jobs"


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

