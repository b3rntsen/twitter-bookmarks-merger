from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
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
        'summary_link',
    ]
    list_filter = ['status', 'error_type', 'scheduled_at']
    search_fields = ['twitter_profile__twitter_username', 'error_message']
    readonly_fields = [
        'scheduled_at', 'started_at', 'completed_at',
        'bookmarks_fetched', 'pages_fetched', 'error_type',
        'summary_display', 'raw_log_display'
    ]
    exclude = ['error_message']
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
        ('Summary', {
            'fields': ('summary_display',),
        }),
        ('Raw Logs', {
            'fields': ('raw_log_display',),
            'classes': ('collapse',),
            'description': 'Tip: search by tweet ID in the list view to find which job processed it.',
        }),
    )

    def get_urls(self):
        """Add per-job log URL."""
        custom = [
            path('<int:job_id>/logs/',
                 self.admin_site.admin_view(self.job_logs_view),
                 name='twitter_bookmarksyncjob_logs'),
        ]
        return custom + super().get_urls()

    def job_logs_view(self, request, job_id):
        """Return structured log as JSON (for modal) or HTML (for direct view)."""
        try:
            job = BookmarkSyncJob.objects.get(id=job_id)
        except BookmarkSyncJob.DoesNotExist:
            return JsonResponse({'error': 'Job not found'}, status=404)

        log = job.error_message or ''
        summary = self._parse_section(log, 'SUMMARY')
        birdmarks = self._parse_section(log, 'BIRDMARKS OUTPUT')
        pipeline = self._parse_section(log, 'PIPELINE LOG')

        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'id': job.id, 'status': job.status,
                'completed_at': str(job.completed_at),
                'summary': summary, 'birdmarks': birdmarks, 'pipeline': pipeline,
            })

        # HTML page (linkable, also used as modal content via fetch)
        import html
        return JsonResponse({
            'html': (
                f'<div style="font-family:monospace;font-size:13px;color:#e0e0e0;">'
                f'<h3 style="color:#a0d0a0;">Job #{job.id} | {job.status} | {job.completed_at}</h3>'
                f'<h4 style="color:#71767b;">Summary</h4>'
                f'<div style="background:#1a2e1a;color:#a0d0a0;padding:8px;border-radius:8px;">'
                f'{html.escape(summary or "No summary")}</div>'
                f'<h4 style="color:#71767b;margin-top:16px;">Birdmarks Output</h4>'
                f'<pre style="background:#1a1a2e;padding:12px;border-radius:8px;'
                f'max-height:400px;overflow:auto;white-space:pre-wrap;word-break:break-word;">'
                f'{html.escape(birdmarks or "No output")}</pre>'
                f'<h4 style="color:#71767b;margin-top:16px;">Pipeline Log</h4>'
                f'<pre style="background:#1a1a2e;padding:12px;border-radius:8px;'
                f'max-height:300px;overflow:auto;white-space:pre-wrap;word-break:break-word;">'
                f'{html.escape(pipeline or "No pipeline log")}</pre>'
                f'</div>'
            )
        })

    def _parse_section(self, log, section):
        """Extract a section from structured log."""
        marker = f"--- {section} ---"
        if marker not in log:
            return ''
        rest = log.split(marker, 1)[1]
        next_marker = rest.find('\n--- ')
        if next_marker > 0:
            return rest[:next_marker].strip()
        return rest.strip()

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

    def summary_link(self, obj):
        """Summary with clickable link to open logs modal."""
        log = obj.error_message or ''
        summary = self._parse_section(log, 'SUMMARY')
        if not summary:
            if '--- RESULT ---' in log:
                summary = log.split('--- RESULT ---')[-1].strip()[:120]
            else:
                summary = '-'
        return format_html(
            '<a href="#" onclick="openLogModal({}); return false;" '
            'title="Click to view full logs">{}</a>'
            '<script>'
            'if (!window._logModalInit) {{'
            '  window._logModalInit = true;'
            '  const d = document.createElement("dialog");'
            '  d.id = "log-modal";'
            '  d.style.cssText = "background:#16181c;color:#e0e0e0;border:1px solid #2f3336;'
            'border-radius:12px;max-width:800px;width:90%;max-height:80vh;padding:20px;";'
            '  d.innerHTML = \'<div id="log-modal-content"></div>'
            '<button onclick="this.closest(\\\'dialog\\\').close()" '
            'style="position:sticky;bottom:0;margin-top:16px;padding:8px 24px;'
            'background:#2f3336;color:#e0e0e0;border:none;border-radius:8px;cursor:pointer;">'
            'Close</button>\';'
            '  document.body.appendChild(d);'
            '  d.addEventListener("click", e => {{ if(e.target===d) d.close(); }});'
            '}}'
            'function openLogModal(jobId) {{'
            '  fetch("/admin/twitter/bookmarksyncjob/" + jobId + "/logs/")'
            '  .then(r => r.json())'
            '  .then(data => {{'
            '    document.getElementById("log-modal-content").innerHTML = data.html;'
            '    document.getElementById("log-modal").showModal();'
            '    history.replaceState(null, "", "/admin/twitter/bookmarksyncjob/" + jobId + "/logs/");'
            '  }});'
            '}}'
            '</script>',
            obj.id, summary[:120]
        )
    summary_link.short_description = "Summary"

    def summary_display(self, obj):
        """Summary section in detail view."""
        log = obj.error_message or ''
        summary = self._parse_section(log, 'SUMMARY')
        if not summary:
            summary = 'No summary available'
        return format_html(
            '<div style="font-size:14px; padding:8px; background:#1a2e1a; '
            'color:#a0d0a0; border-radius:8px;">{}</div>',
            summary
        )
    summary_display.short_description = "Summary"

    def raw_log_display(self, obj):
        """Full raw log in detail view."""
        log = obj.error_message or ''
        birdmarks = self._parse_section(log, 'BIRDMARKS OUTPUT')
        pipeline = self._parse_section(log, 'PIPELINE LOG')
        if not birdmarks and not pipeline:
            full_log = log
        else:
            full_log = ''
            if birdmarks:
                full_log += f"=== Birdmarks Output ===\n{birdmarks}\n\n"
            if pipeline:
                full_log += f"=== Pipeline Log ===\n{pipeline}"
        if not full_log.strip():
            full_log = 'No raw logs available'
        return format_html(
            '<pre style="background:#1a1a2e; color:#e0e0e0; padding:12px; '
            'border-radius:8px; max-height:600px; overflow:auto; '
            'font-family:monospace; font-size:12px; white-space:pre-wrap; '
            'word-break:break-word;">{}</pre>',
            full_log
        )
    raw_log_display.short_description = "Raw Logs"

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

