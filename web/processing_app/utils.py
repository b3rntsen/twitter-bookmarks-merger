"""
Utility functions for content processing.
"""
from datetime import date, timedelta
from django.contrib.auth.models import User
from processing_app.models import DailyContentSnapshot


def get_today_utc() -> date:
    """
    Get today's date in UTC for consistent date filtering.
    
    Returns:
        date: Today's date in UTC
    """
    from django.utils import timezone
    return timezone.now().date()


def get_available_dates(user: User) -> list:
    """
    Get list of available processing dates for a user.
    
    Args:
        user: User instance
        
    Returns:
        List of date objects, sorted descending (most recent first)
    """
    dates = DailyContentSnapshot.objects.filter(
        user=user
    ).values_list('processing_date', flat=True).distinct().order_by('-processing_date')
    
    return list(dates)


def get_previous_date(current_date: date) -> date:
    """
    Get the previous day's date.
    
    Args:
        current_date: Current date
        
    Returns:
        date: Previous day
    """
    return current_date - timedelta(days=1)


def get_next_date(current_date: date) -> date:
    """
    Get the next day's date.
    
    Args:
        current_date: Current date
        
    Returns:
        date: Next day
    """
    return current_date + timedelta(days=1)


def get_date_navigation_context(user: User, current_date: date) -> dict:
    """
    Get context data for date navigation UI.
    
    Args:
        user: User instance
        current_date: Currently selected date
        
    Returns:
        Dict with navigation context:
        - current_date: Current date
        - previous_date: Previous day
        - next_date: Next day
        - available_dates: List of available dates
        - has_previous: bool
        - has_next: bool
    """
    available_dates = get_available_dates(user)
    previous_date = get_previous_date(current_date)
    next_date = get_next_date(current_date)
    
    return {
        'current_date': current_date,
        'previous_date': previous_date,
        'next_date': next_date,
        'available_dates': available_dates,
        'has_previous': previous_date in available_dates,
        'has_next': next_date in available_dates,
        'is_today': current_date == get_today_utc(),
    }


def get_processing_status_info(user: User, target_date: date = None) -> dict:
    """
    Get processing status information for a user and date.
    
    Args:
        user: User instance
        target_date: Date to check status for (defaults to today)
        
    Returns:
        Dict with processing status:
        - is_processing: bool - Are there active jobs?
        - next_processing_time: datetime - When will next processing run?
        - estimated_processing_time: int - Estimated minutes for processing
        - has_content: bool - Does this date have processed content?
    """
    from django.utils import timezone
    from processing_app.models import ContentProcessingJob, ProcessingSchedule, DailyContentSnapshot
    from twitter.models import TwitterProfile
    
    if target_date is None:
        target_date = get_today_utc()
    
    try:
        twitter_profile = TwitterProfile.objects.get(user=user)
    except TwitterProfile.DoesNotExist:
        return {
            'is_processing': False,
            'next_processing_time': None,
            'estimated_processing_time': None,
            'has_content': False,
        }
    
    # Check for active jobs
    active_jobs = ContentProcessingJob.objects.filter(
        user=user,
        processing_date=target_date,
        status__in=['running', 'pending', 'retrying']
    ).exists()
    
    # Get processing schedule
    try:
        processing_schedule = ProcessingSchedule.objects.get(user=user)
    except ProcessingSchedule.DoesNotExist:
        processing_schedule = None
    
    # Calculate next processing time
    next_processing_time = None
    if processing_schedule and processing_schedule.enabled:
        from processing_app.schedulers import DailyScheduler
        scheduler = DailyScheduler()
        next_processing_time = scheduler._get_schedule_time(processing_schedule, target_date)
    
    # Estimate processing time from historical data
    estimated_processing_time = None
    recent_completed = ContentProcessingJob.objects.filter(
        user=user,
        status='completed',
        completed_at__isnull=False,
        started_at__isnull=False
    ).order_by('-completed_at')[:10]
    
    if recent_completed.exists():
        total_duration = sum(
            (job.completed_at - job.started_at).total_seconds()
            for job in recent_completed
            if job.completed_at and job.started_at
        )
        avg_duration = total_duration / recent_completed.count() if recent_completed.count() > 0 else 0
        estimated_processing_time = int(avg_duration / 60)  # Convert to minutes
    
    # Check if content exists for this date
    has_content = DailyContentSnapshot.objects.filter(
        user=user,
        twitter_profile=twitter_profile,
        processing_date=target_date,
        total_tweet_count__gt=0
    ).exists()
    
    return {
        'is_processing': active_jobs,
        'next_processing_time': next_processing_time,
        'estimated_processing_time': estimated_processing_time,
        'has_content': has_content,
    }

