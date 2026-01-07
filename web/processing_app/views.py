"""
Views for processing status and history.
"""
import logging
import json
import time
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.http import StreamingHttpResponse
from datetime import date, timedelta
from processing_app.models import ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot
from processing_app.schedulers import DailyScheduler
from twitter.models import TwitterProfile

logger = logging.getLogger(__name__)


@login_required
def processing_status(request):
    """Display processing status and history for the current user."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return redirect('twitter:connect')
    
    # Get processing schedule
    try:
        processing_schedule = ProcessingSchedule.objects.get(user=request.user)
    except ProcessingSchedule.DoesNotExist:
        processing_schedule = None
    
    # Get latest jobs (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    latest_jobs_queryset = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        created_at__gte=thirty_days_ago
    ).order_by('-processing_date', '-created_at')
    
    # Get job counts by status
    job_counts = {
        'pending': ContentProcessingJob.objects.filter(
            user=request.user,
            status='pending'
        ).count(),
        'running': ContentProcessingJob.objects.filter(
            user=request.user,
            status='running'
        ).count(),
        'completed': ContentProcessingJob.objects.filter(
            user=request.user,
            status='completed'
        ).count(),
        'failed': ContentProcessingJob.objects.filter(
            user=request.user,
            status='failed'
        ).count(),
        'retrying': ContentProcessingJob.objects.filter(
            user=request.user,
            status='retrying'
        ).count(),
    }
    
    # Get latest snapshot
    latest_snapshot = DailyContentSnapshot.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile
    ).order_by('-processing_date').first()
    
    # Get recent snapshots (last 7 days) - evaluate immediately
    recent_snapshots = list(DailyContentSnapshot.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile
    ).order_by('-processing_date')[:7])
    
    # Calculate next processing time
    next_processing_time = None
    if processing_schedule and processing_schedule.enabled:
        from datetime import datetime, time as dt_time
        from processing_app.schedulers import DailyScheduler
        scheduler = DailyScheduler()
        # Get next scheduled time (private method, but safe to use)
        try:
            next_processing_time = scheduler._get_schedule_time(processing_schedule, date.today())
        except AttributeError:
            # Fallback: calculate manually
            processing_time = processing_schedule.processing_time
            next_processing_time = timezone.make_aware(
                datetime.combine(date.today(), processing_time),
                timezone.utc
            )
            if next_processing_time < timezone.now():
                next_processing_time += timedelta(days=1)
    
    # Estimate processing time based on historical data
    estimated_processing_time = None
    if latest_snapshot and latest_snapshot.last_processed_at:
        # Get average processing time from recent completed jobs
        recent_completed = ContentProcessingJob.objects.filter(
            user=request.user,
            status='completed',
            completed_at__isnull=False,
            started_at__isnull=False
        ).order_by('-completed_at')[:10]
        
        # Evaluate queryset immediately to avoid async issues
        recent_completed_list = list(recent_completed)
        if recent_completed_list:
            total_duration = sum(
                (job.completed_at - job.started_at).total_seconds()
                for job in recent_completed_list
                if job.completed_at and job.started_at
            )
            avg_duration = total_duration / len(recent_completed_list) if recent_completed_list else 0
            estimated_processing_time = int(avg_duration / 60)  # Convert to minutes
    
    # Check if there are active jobs (running or pending)
    active_jobs = ContentProcessingJob.objects.filter(
        user=request.user,
        status__in=['running', 'pending', 'retrying']
    ).exists()
    
    # Check if jobs exist for today
    today = date.today()
    today_jobs = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        processing_date=today
    )
    today_jobs_exist = today_jobs.exists()
    today_jobs_complete = today_jobs.filter(status='completed').count()
    today_jobs_total = today_jobs.count()
    
    # Check if all today's jobs are in terminal states (failed) - allows re-triggering
    # Terminal states are: 'failed' (includes cancelled jobs)
    # Non-terminal states are: 'pending', 'running', 'retrying', 'completed'
    today_jobs_active = today_jobs.exclude(status__in=['failed', 'completed']).exists()
    today_jobs_all_failed = today_jobs_exist and not today_jobs_active and today_jobs_complete == 0
    today_jobs_failed = today_jobs.filter(status='failed').count()
    
    # Show trigger button if:
    # 1. No jobs exist for today, OR
    # 2. All jobs for today are failed (terminal state) and no active jobs
    show_trigger_button = not today_jobs_exist or (today_jobs_all_failed and not active_jobs)
    
    # Show force start button if there are any failed jobs or if some jobs are completed
    show_force_start_button = today_jobs_failed > 0 or (today_jobs_complete > 0 and today_jobs_complete < today_jobs_total)
    
    # Get job status per content type for worker management
    content_type_status = {}
    for content_type in ['bookmarks', 'curated_feed', 'lists']:
        type_jobs = ContentProcessingJob.objects.filter(
            user=request.user,
            twitter_profile=twitter_profile,
            content_type=content_type,
            processing_date=today
        )
        content_type_status[content_type] = {
            'pending': type_jobs.filter(status='pending').count(),
            'running': type_jobs.filter(status='running').count(),
            'completed': type_jobs.filter(status='completed').count(),
            'failed': type_jobs.filter(status='failed').count(),
            'retrying': type_jobs.filter(status='retrying').count(),
            'total': type_jobs.count(),
            'has_active': type_jobs.filter(status__in=['pending', 'running', 'retrying']).exists(),
        }
    
    # Get schedule status for each content type
    if processing_schedule:
        content_type_status['bookmarks']['enabled'] = processing_schedule.process_bookmarks
        content_type_status['curated_feed']['enabled'] = processing_schedule.process_curated_feed
        content_type_status['lists']['enabled'] = processing_schedule.process_lists
    else:
        # Default to enabled if no schedule exists
        for content_type in ['bookmarks', 'curated_feed', 'lists']:
            content_type_status[content_type]['enabled'] = True
    
    # Convert queryset to list first to force evaluation and avoid async issues
    # Get all jobs first, then paginate manually
    all_jobs_list = list(latest_jobs_queryset[:50])
    
    # Pre-calculate all job data to avoid async context issues in template
    job_tweet_counts = {}
    jobs_with_data = []
    
    for job in all_jobs_list:
        # Pre-calculate all values that might cause async issues
        # This includes database queries, so do it all here
        job_tweet_counts[job.id] = job.get_tweets_saved_count()
        # Store job with pre-calculated display values as attributes
        job.content_type_display = job.get_content_type_display()
        job.status_display = job.get_status_display()
        # Pre-access all fields that might be lazy
        _ = job.processing_date
        _ = job.items_processed
        _ = job.retry_count
        _ = job.max_retries
        _ = job.completed_at
        _ = job.error_message
        jobs_with_data.append(job)
    
    # Manual pagination to avoid any lazy evaluation
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1
    
    per_page = 20
    total_jobs = len(jobs_with_data)
    total_pages = (total_jobs + per_page - 1) // per_page if total_jobs > 0 else 1
    page_number = max(1, min(page_number, total_pages))
    
    start_idx = (page_number - 1) * per_page
    end_idx = start_idx + per_page
    page_jobs = jobs_with_data[start_idx:end_idx]
    
    # Create a simple page-like object for template compatibility
    class SimplePage:
        def __init__(self, object_list, number, num_pages, has_previous, has_next):
            self.object_list = object_list
            self.number = number
            self.num_pages = num_pages
            self.has_previous = has_previous
            self.has_next = has_next
            if number > 1:
                self.previous_page_number = number - 1
            else:
                self.previous_page_number = None
            if number < num_pages:
                self.next_page_number = number + 1
            else:
                self.next_page_number = None
        
        def __iter__(self):
            """Make SimplePage iterable so template can loop over it."""
            return iter(self.object_list)
        
        def __len__(self):
            """Return length of object_list."""
            return len(self.object_list)
    
    page_obj = SimplePage(
        object_list=page_jobs,
        number=page_number,
        num_pages=total_pages,
        has_previous=page_number > 1,
        has_next=page_number < total_pages
    )
    
    # Get list processing status for foldable widget (US5)
    from lists_app.models import TwitterList, ListTweet
    
    list_processing_status = []
    user_lists = TwitterList.objects.filter(twitter_profile=twitter_profile).order_by('list_name')
    
    for twitter_list in user_lists:
        # Get tweet count for selected date (today by default)
        list_tweet_count = ListTweet.objects.filter(
            twitter_list=twitter_list,
            seen_date=today
        ).count()
        
        # Get processing status for this list
        list_job = ContentProcessingJob.objects.filter(
            user=request.user,
            twitter_profile=twitter_profile,
            content_type='lists',
            processing_date=today
        ).first()
        
        status = 'pending'
        if list_job:
            status = list_job.status
        elif list_tweet_count > 0:
            # If we have tweets but no job, assume completed
            status = 'completed'
        
        # Get last processed timestamp
        last_processed = None
        if list_job and list_job.completed_at:
            last_processed = list_job.completed_at
        elif twitter_list.last_synced_at:
            last_processed = twitter_list.last_synced_at
        
        list_processing_status.append({
            'list_id': twitter_list.id,
            'list_name': twitter_list.list_name,
            'tweet_count': list_tweet_count,
            'status': status,
            'last_processed': last_processed,
        })
    
    context = {
        'twitter_profile': twitter_profile,
        'processing_schedule': processing_schedule,
        'latest_jobs': page_obj,
        'job_tweet_counts': job_tweet_counts,
        'job_counts': job_counts,
        'latest_snapshot': latest_snapshot,
        'recent_snapshots': recent_snapshots,
        'next_processing_time': next_processing_time,
        'estimated_processing_time': estimated_processing_time,
        'active_jobs': active_jobs,
        'today_jobs_exist': today_jobs_exist,
        'today_jobs_complete': today_jobs_complete,
        'today_jobs_total': today_jobs_total,
        'today_jobs_all_failed': today_jobs_all_failed,
        'today_jobs_failed': today_jobs_failed,
        'show_trigger_button': show_trigger_button,
        'show_force_start_button': show_force_start_button,
        'today': today,
        'content_type_status': content_type_status,
        'list_processing_status': list_processing_status,  # US5
    }
    
    return render(request, 'processing_app/status.html', context)


@login_required
@require_POST
def trigger_today_jobs(request):
    """Manually trigger scheduling and immediate processing of today's jobs."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    scheduler = DailyScheduler()
    today = date.today()
    
    # Schedule jobs for today with immediate processing
    jobs = scheduler.schedule_user_jobs(
        user=request.user,
        target_date=today,
        immediate=True
    )
    
    if jobs:
        messages.success(
            request,
            f"Successfully queued {len(jobs)} job(s) for immediate processing today."
        )
    else:
        # Check if jobs already exist
        existing_jobs = ContentProcessingJob.objects.filter(
            user=request.user,
            twitter_profile=twitter_profile,
            processing_date=today
        )
        if existing_jobs.exists():
            messages.info(
                request,
                f"Jobs for today already exist ({existing_jobs.count()} job(s)). "
                "They will be processed automatically."
            )
        else:
            messages.warning(
                request,
                "No jobs were created. Please check your processing schedule configuration."
            )
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def force_start_all_jobs(request):
    """Force start all jobs for today, resetting failed and completed ones."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    scheduler = DailyScheduler()
    today = date.today()
    
    # Get all existing jobs for today
    existing_jobs = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        processing_date=today
    )
    
    # Get existing content types
    existing_content_types = set(existing_jobs.values_list('content_type', flat=True))
    
    # Reset all existing jobs
    reset_count = 0
    from django_q.tasks import async_task
    
    for job in existing_jobs:
        job.status = 'pending'
        job.retry_count = 0
        job.scheduled_at = timezone.now()
        job.started_at = None
        job.completed_at = None
        job.next_retry_at = None
        job.error_message = ''
        job.error_traceback = ''
        job.items_processed = 0
        job.save()
        reset_count += 1
        
        # Queue immediately
        async_task('processing_app.tasks.process_content_job', job.id)
    
    # Get processing schedule to determine which content types should exist
    try:
        processing_schedule = ProcessingSchedule.objects.get(user=request.user)
    except ProcessingSchedule.DoesNotExist:
        processing_schedule = None
    
    # Create any missing jobs (only for content types that don't already exist)
    # Use get_or_create to avoid race conditions
    new_jobs = []
    if processing_schedule and processing_schedule.enabled:
        content_type_map = {
            'bookmarks': processing_schedule.process_bookmarks,
            'curated_feed': processing_schedule.process_curated_feed,
            'lists': processing_schedule.process_lists,
        }
        
        for content_type, is_enabled in content_type_map.items():
            if is_enabled and content_type not in existing_content_types:
                # Use get_or_create to avoid unique constraint violation
                job, created = ContentProcessingJob.objects.get_or_create(
                    user=request.user,
                    twitter_profile=twitter_profile,
                    content_type=content_type,
                    processing_date=today,
                    defaults={
                        'status': 'pending',
                        'scheduled_at': timezone.now(),
                        'retry_count': 0,
                        'max_retries': 5
                    }
                )
                if created:
                    new_jobs.append(job)
                    # Queue immediately
                    async_task('processing_app.tasks.process_content_job', job.id)
                else:
                    # Job was created between our check and now, reset it
                    job.status = 'pending'
                    job.retry_count = 0
                    job.scheduled_at = timezone.now()
                    job.started_at = None
                    job.completed_at = None
                    job.next_retry_at = None
                    job.error_message = ''
                    job.error_traceback = ''
                    job.items_processed = 0
                    job.save()
                    reset_count += 1
                    async_task('processing_app.tasks.process_content_job', job.id)
    
    total_jobs = reset_count + len(new_jobs)
    messages.success(
        request,
        f"Force started {total_jobs} job(s): {reset_count} reset, {len(new_jobs)} newly created."
    )
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def restart_failed_jobs(request):
    """Restart only failed/cancelled jobs for today."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    today = date.today()
    
    # Find all failed jobs for today
    failed_jobs = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        processing_date=today,
        status='failed'
    )
    
    if not failed_jobs.exists():
        messages.info(request, "No failed jobs found to restart.")
        return redirect('processing:processing_status')
    
    reset_count = 0
    from django_q.tasks import async_task
    
    for job in failed_jobs:
        job.status = 'pending'
        job.retry_count = 0
        job.scheduled_at = timezone.now()
        job.started_at = None
        job.completed_at = None
        job.next_retry_at = None
        job.error_message = ''
        job.error_traceback = ''
        job.items_processed = 0
        job.save()
        reset_count += 1
        
        # Queue immediately
        async_task('processing_app.tasks.process_content_job', job.id)
    
    messages.success(
        request,
        f"Restarted {reset_count} failed job(s) for immediate processing."
    )
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def kill_all_jobs(request):
    """Cancel/stop all running and pending jobs for the user."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Get all running/pending/retrying jobs
    jobs_to_kill = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        status__in=['running', 'pending', 'retrying']
    )
    
    count = jobs_to_kill.count()
    
    if count == 0:
        messages.info(request, "No active jobs to cancel.")
        return redirect('processing:processing_status')
    
    # Update job status to 'failed' with cancellation message
    jobs_to_kill.update(
        status='failed',
        error_message='Cancelled by user',
        next_retry_at=None
    )
    
    # Try to cancel Django-Q tasks (if they exist)
    try:
        from django_q.models import Task
        # Find tasks for these job IDs
        job_ids = list(jobs_to_kill.values_list('id', flat=True))
        tasks = Task.objects.filter(
            func='processing_app.tasks.process_content_job',
            args__contains=job_ids
        ).filter(success__isnull=True)  # Only unfinished tasks
        
        # Django-Q doesn't have a direct cancel, but we can mark them
        # The jobs are already marked as failed, so they won't be processed
        task_count = tasks.count()
    except Exception as e:
        task_count = 0
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not cancel Django-Q tasks: {e}")
    
    messages.success(
        request,
        f"Successfully cancelled {count} job(s). "
        f"({task_count} Django-Q task(s) affected)"
    )
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def delete_all_twitter_content(request):
    """Delete all Twitter content for the user (tweets, bookmarks, lists, events, etc.)."""
    from django.db import transaction
    from twitter.models import Tweet, TweetThread, TweetMedia, TweetReply
    from bookmarks_app.models import CuratedFeed, TweetCategory, CategorizedTweet
    from lists_app.models import TwitterList, ListTweet, Event, EventTweet
    
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Confirm deletion
    confirm = request.POST.get('confirm', '').lower()
    if confirm != 'delete':
        messages.error(request, "Please type 'delete' to confirm deletion of all Twitter content.")
        return redirect('processing:processing_status')
    
    try:
        with transaction.atomic():
            # Delete in order to respect foreign key constraints
            
            # 1. Delete EventTweets first (depends on Event and ListTweet)
            event_tweets = EventTweet.objects.filter(
                event__twitter_list__twitter_profile=twitter_profile
            )
            event_tweet_count = event_tweets.count()
            event_tweets.delete()
            
            # 2. Delete Events (depends on TwitterList)
            events = Event.objects.filter(twitter_list__twitter_profile=twitter_profile)
            event_count = events.count()
            events.delete()
            
            # 3. Delete ListTweets (depends on Tweet and TwitterList)
            list_tweets = ListTweet.objects.filter(twitter_list__twitter_profile=twitter_profile)
            list_tweet_count = list_tweets.count()
            list_tweets.delete()
            
            # 4. Delete TwitterLists
            twitter_lists = TwitterList.objects.filter(twitter_profile=twitter_profile)
            list_count = twitter_lists.count()
            twitter_lists.delete()
            
            # 5. Delete CategorizedTweets (depends on Tweet and TweetCategory)
            categorized_tweets = CategorizedTweet.objects.filter(
                tweet__twitter_profile=twitter_profile
            )
            categorized_count = categorized_tweets.count()
            categorized_tweets.delete()
            
            # 6. Delete TweetCategories (depends on CuratedFeed)
            categories = TweetCategory.objects.filter(
                curated_feed__twitter_profile=twitter_profile
            )
            category_count = categories.count()
            categories.delete()
            
            # 7. Delete CuratedFeeds
            curated_feeds = CuratedFeed.objects.filter(twitter_profile=twitter_profile)
            curated_feed_count = curated_feeds.count()
            curated_feeds.delete()
            
            # 8. Delete Tweet-related objects (Thread, Media, Reply) - these depend on Tweet
            tweets = Tweet.objects.filter(twitter_profile=twitter_profile)
            tweet_count = tweets.count()
            
            # Delete related objects first (they have foreign keys to Tweet)
            TweetThread.objects.filter(tweet__twitter_profile=twitter_profile).delete()
            TweetMedia.objects.filter(tweet__twitter_profile=twitter_profile).delete()
            TweetReply.objects.filter(tweet__twitter_profile=twitter_profile).delete()
            
            # Delete Tweets (this will also cascade delete any remaining references)
            tweets.delete()
            
            # 9. Delete processing jobs and snapshots
            processing_jobs = ContentProcessingJob.objects.filter(
                user=request.user,
                twitter_profile=twitter_profile
            )
            job_count = processing_jobs.count()
            processing_jobs.delete()
            
            snapshots = DailyContentSnapshot.objects.filter(
                user=request.user,
                twitter_profile=twitter_profile
            )
            snapshot_count = snapshots.count()
            snapshots.delete()
            
            # Summary
            total_deleted = (
                tweet_count + 
                curated_feed_count + 
                category_count + 
                categorized_count +
                list_count +
                list_tweet_count +
                event_count +
                event_tweet_count
            )
            
            messages.success(
                request,
                f"Successfully deleted all Twitter content:\n"
                f"- {tweet_count} tweets\n"
                f"- {curated_feed_count} curated feeds, {category_count} categories\n"
                f"- {list_count} lists, {list_tweet_count} list tweets\n"
                f"- {event_count} events, {event_tweet_count} event tweets\n"
                f"- {job_count} processing jobs, {snapshot_count} snapshots\n"
                f"Total: {total_deleted} content items deleted."
            )
            
    except Exception as e:
        messages.error(
            request,
            f"Error deleting content: {str(e)}. Please try again or contact support."
        )
        logger.exception("Error deleting all Twitter content")
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def toggle_content_type(request, content_type):
    """
    Toggle enable/disable for a specific content type in ProcessingSchedule.
    
    Args:
        content_type: 'bookmarks', 'curated_feed', or 'lists'
    """
    if content_type not in ['bookmarks', 'curated_feed', 'lists']:
        messages.error(request, f"Invalid content type: {content_type}")
        return redirect('processing:processing_status')
    
    # Get or create processing schedule
    schedule, created = ProcessingSchedule.objects.get_or_create(
        user=request.user,
        defaults={
            'enabled': True,
            'process_bookmarks': True,
            'process_curated_feed': True,
            'process_lists': True,
        }
    )
    
    # Toggle the content type
    field_name = f'process_{content_type}'
    current_value = getattr(schedule, field_name)
    setattr(schedule, field_name, not current_value)
    schedule.save(update_fields=[field_name])
    
    status = "enabled" if not current_value else "disabled"
    content_type_display = content_type.replace('_', ' ').title()
    messages.success(request, f"{content_type_display} processing {status}")
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def start_content_type(request, content_type):
    """
    Start processing for a specific content type immediately.
    
    Args:
        content_type: 'bookmarks', 'curated_feed', or 'lists'
    """
    if content_type not in ['bookmarks', 'curated_feed', 'lists']:
        messages.error(request, f"Invalid content type: {content_type}")
        return redirect('processing:processing_status')
    
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Check if content type is enabled
    try:
        schedule = ProcessingSchedule.objects.get(user=request.user)
        if not getattr(schedule, f'process_{content_type}', False):
            content_type_display = content_type.replace('_', ' ').title()
            messages.warning(
                request,
                f"{content_type_display} is disabled. Enable it first to start processing."
            )
            return redirect('processing:processing_status')
    except ProcessingSchedule.DoesNotExist:
        pass  # Default to enabled if no schedule exists
    
    today = date.today()
    
    # Get or create job for this content type
    job, created = ContentProcessingJob.objects.get_or_create(
        user=request.user,
        twitter_profile=twitter_profile,
        content_type=content_type,
        processing_date=today,
        defaults={
            'status': 'pending',
            'scheduled_at': timezone.now(),
            'retry_count': 0,
            'max_retries': 5,
        }
    )
    
    if not created:
        # Job already exists - reset it and queue it
        job.status = 'pending'
        job.retry_count = 0
        job.scheduled_at = timezone.now()
        job.started_at = None
        job.completed_at = None
        job.next_retry_at = None
        job.error_message = ''
        job.error_traceback = ''
        job.items_processed = 0
        job.save()
    
    # Queue the job immediately
    from django_q.tasks import async_task
    async_task(
        'processing_app.tasks.process_content_job',
        job.id,
        hook='processing_app.tasks.job_completion_hook'
    )
    
    content_type_display = content_type.replace('_', ' ').title()
    messages.success(
        request,
        f"Started processing {content_type_display}. Job ID: {job.id}"
    )
    
    return redirect('processing:processing_status')


@login_required
@require_POST
def stop_content_type(request, content_type):
    """
    Stop/cancel all running and pending jobs for a specific content type.
    
    Args:
        content_type: 'bookmarks', 'curated_feed', or 'lists'
    """
    if content_type not in ['bookmarks', 'curated_feed', 'lists']:
        messages.error(request, f"Invalid content type: {content_type}")
        return redirect('processing:processing_status')
    
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Get all running/pending/retrying jobs for this content type
    jobs_to_kill = ContentProcessingJob.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        content_type=content_type,
        status__in=['running', 'pending', 'retrying']
    )
    
    count = jobs_to_kill.count()
    
    if count == 0:
        content_type_display = content_type.replace('_', ' ').title()
        messages.info(request, f"No active {content_type_display} jobs to cancel.")
        return redirect('processing:processing_status')
    
    # Update job status to 'failed' with cancellation message
    jobs_to_kill.update(
        status='failed',
        error_message='Cancelled by user',
        next_retry_at=None
    )
    
    content_type_display = content_type.replace('_', ' ').title()
    messages.success(
        request,
        f"Successfully cancelled {count} {content_type_display} job(s)."
    )
    
    return redirect('processing:processing_status')


@login_required
def sse_status_stream(request):
    """
    Stream Server-Sent Events (SSE) for real-time processing status updates.
    
    Per contracts/sse-stream-interface.md:
    - Streams events when job states change
    - Streams worker status changes
    - Streams tweet count updates
    - User-scoped (only user's own data)
    """
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        # Return empty stream if no Twitter profile
        def empty_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': 'No Twitter profile connected'})}\n\n"
            time.sleep(1)
        
        response = StreamingHttpResponse(empty_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
    
    def event_stream():
        """Generator that yields SSE events."""
        last_state = {
            'job_counts': {},
            'worker_status': {},
            'tweet_counts': {},
            'jobs': set(),
        }
        
        # Send initial state
        try:
            # Get initial job counts
            job_counts = {
                'pending': ContentProcessingJob.objects.filter(
                    user=request.user,
                    status='pending'
                ).count(),
                'running': ContentProcessingJob.objects.filter(
                    user=request.user,
                    status='running'
                ).count(),
                'completed': ContentProcessingJob.objects.filter(
                    user=request.user,
                    status='completed'
                ).count(),
                'failed': ContentProcessingJob.objects.filter(
                    user=request.user,
                    status='failed'
                ).count(),
                'retrying': ContentProcessingJob.objects.filter(
                    user=request.user,
                    status='retrying'
                ).count(),
            }
            last_state['job_counts'] = job_counts
            
            # Get initial worker status
            try:
                schedule = ProcessingSchedule.objects.get(user=request.user)
                worker_status = {
                    'bookmarks': {'enabled': schedule.process_bookmarks, 'active': False},
                    'curated_feed': {'enabled': schedule.process_curated_feed, 'active': False},
                    'lists': {'enabled': schedule.process_lists, 'active': False},
                }
            except ProcessingSchedule.DoesNotExist:
                worker_status = {
                    'bookmarks': {'enabled': True, 'active': False},
                    'curated_feed': {'enabled': True, 'active': False},
                    'lists': {'enabled': True, 'active': False},
                }
            
            # Check active status
            today = date.today()
            for content_type in ['bookmarks', 'curated_feed', 'lists']:
                has_active = ContentProcessingJob.objects.filter(
                    user=request.user,
                    twitter_profile=twitter_profile,
                    content_type=content_type,
                    processing_date=today,
                    status__in=['running', 'pending', 'retrying']
                ).exists()
                worker_status[content_type]['active'] = has_active
            
            last_state['worker_status'] = worker_status
            
            # Get initial tweet counts
            from twitter.models import Tweet
            total_tweets = Tweet.objects.filter(
                twitter_profile=twitter_profile
            ).count()
            
            today_tweets = Tweet.objects.filter(
                twitter_profile=twitter_profile,
                processing_date=today
            ).count()
            
            tweet_counts = {
                'total': total_tweets,
                'today': today_tweets,
            }
            last_state['tweet_counts'] = tweet_counts
            
            # Send initial state event
            init_event = {
                'type': 'init',
                'data': {
                    'job_counts': job_counts,
                    'worker_status': worker_status,
                    'tweet_counts': tweet_counts,
                }
            }
            yield f"data: {json.dumps(init_event)}\n\n"
            
        except Exception as e:
            logger.exception("Error generating initial SSE state")
            error_event = {
                'type': 'error',
                'message': f'Error initializing: {str(e)}'
            }
            yield f"data: {json.dumps(error_event)}\n\n"
            return
        
        # Poll for changes
        poll_interval = 0.75  # Poll every 0.75 seconds
        max_iterations = 2400  # ~30 minutes max (2400 * 0.75 = 1800 seconds)
        iteration = 0
        
        while iteration < max_iterations:
            try:
                # Check for job count changes
                current_job_counts = {
                    'pending': ContentProcessingJob.objects.filter(
                        user=request.user,
                        status='pending'
                    ).count(),
                    'running': ContentProcessingJob.objects.filter(
                        user=request.user,
                        status='running'
                    ).count(),
                    'completed': ContentProcessingJob.objects.filter(
                        user=request.user,
                        status='completed'
                    ).count(),
                    'failed': ContentProcessingJob.objects.filter(
                        user=request.user,
                        status='failed'
                    ).count(),
                    'retrying': ContentProcessingJob.objects.filter(
                        user=request.user,
                        status='retrying'
                    ).count(),
                }
                
                if current_job_counts != last_state['job_counts']:
                    event = {
                        'type': 'job_counts',
                        'data': current_job_counts
                    }
                    yield f"data: {json.dumps(event)}\n\n"
                    last_state['job_counts'] = current_job_counts
                
                # Check for worker status changes
                try:
                    schedule = ProcessingSchedule.objects.get(user=request.user)
                    current_worker_status = {
                        'bookmarks': {'enabled': schedule.process_bookmarks, 'active': False},
                        'curated_feed': {'enabled': schedule.process_curated_feed, 'active': False},
                        'lists': {'enabled': schedule.process_lists, 'active': False},
                    }
                except ProcessingSchedule.DoesNotExist:
                    current_worker_status = {
                        'bookmarks': {'enabled': True, 'active': False},
                        'curated_feed': {'enabled': True, 'active': False},
                        'lists': {'enabled': True, 'active': False},
                    }
                
                # Check active status
                for content_type in ['bookmarks', 'curated_feed', 'lists']:
                    has_active = ContentProcessingJob.objects.filter(
                        user=request.user,
                        twitter_profile=twitter_profile,
                        content_type=content_type,
                        processing_date=today,
                        status__in=['running', 'pending', 'retrying']
                    ).exists()
                    current_worker_status[content_type]['active'] = has_active
                
                if current_worker_status != last_state['worker_status']:
                    # Send individual worker status updates
                    for content_type, status in current_worker_status.items():
                        if status != last_state['worker_status'].get(content_type):
                            event = {
                                'type': 'worker_status',
                                'data': {
                                    'content_type': content_type,
                                    'enabled': status['enabled'],
                                    'active': status['active'],
                                }
                            }
                            yield f"data: {json.dumps(event)}\n\n"
                    last_state['worker_status'] = current_worker_status
                
                # Check for tweet count changes
                from twitter.models import Tweet
                current_total = Tweet.objects.filter(
                    twitter_profile=twitter_profile
                ).count()
                
                current_today = Tweet.objects.filter(
                    twitter_profile=twitter_profile,
                    processing_date=today
                ).count()
                
                current_tweet_counts = {
                    'total': current_total,
                    'today': current_today,
                }
                
                if current_tweet_counts != last_state['tweet_counts']:
                    event = {
                        'type': 'tweet_counts',
                        'data': current_tweet_counts
                    }
                    yield f"data: {json.dumps(event)}\n\n"
                    last_state['tweet_counts'] = current_tweet_counts
                
                # Check for individual job updates (recent jobs only)
                thirty_days_ago = timezone.now() - timedelta(days=30)
                recent_jobs = ContentProcessingJob.objects.filter(
                    user=request.user,
                    twitter_profile=twitter_profile,
                    created_at__gte=thirty_days_ago
                ).order_by('-created_at')[:20]
                
                current_job_ids = {job.id for job in recent_jobs}
                last_job_ids = last_state.get('jobs', set())
                
                # Check for new or updated jobs
                for job in recent_jobs:
                    job_key = (job.id, job.status, job.items_processed)
                    last_job_key = None
                    for last_id in last_job_ids:
                        if isinstance(last_id, tuple) and last_id[0] == job.id:
                            last_job_key = last_id
                            break
                    
                    if job_key != last_job_key:
                        event = {
                            'type': 'job_update',
                            'data': {
                                'job_id': job.id,
                                'status': job.status,
                                'content_type': job.content_type,
                                'items_processed': job.items_processed,
                                'processing_date': job.processing_date.isoformat() if job.processing_date else None,
                            }
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                
                # Update last state
                last_state['jobs'] = {(job.id, job.status, job.items_processed) for job in recent_jobs}
                
                # Sleep before next poll
                time.sleep(poll_interval)
                iteration += 1
                
            except Exception as e:
                logger.exception("Error in SSE event stream")
                error_event = {
                    'type': 'error',
                    'message': f'Error: {str(e)}'
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                time.sleep(poll_interval)
                iteration += 1
    
    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response

