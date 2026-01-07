"""
Views for the lists app - list selection and event display.
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from datetime import date, timedelta
# threading import kept for deprecated functions (not actively used)
import traceback
from twitter.models import TwitterProfile
from .models import TwitterList, Event, ListTweet
from .services import ListsService
from .event_service import EventService


def _sync_lists_in_thread(profile_id, use_playwright):
    """
    DEPRECATED: This function is no longer used.
    List syncing is now handled by processing_app processors via Django-Q.
    This function is kept for backward compatibility but should not be called.
    
    @deprecated Use processing_app.processors.ListProcessor instead
    """
    """Background task to sync lists - runs in a separate thread to avoid async context issues."""
    from django.db import connection
    
    # Close any existing database connections to avoid issues
    connection.close()
    
    lists_service = None
    try:
        print(f"[SYNC LISTS TASK] Starting sync for profile_id={profile_id}, use_playwright={use_playwright}")
        
        # Get fresh profile instance in this thread
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Initialize service
        lists_service = None
        try:
            lists_service = ListsService(profile, use_playwright=use_playwright)
            
            # Fetch lists from Twitter
            print(f"[SYNC LISTS TASK] Fetching lists from Twitter...")
            twitter_lists = lists_service.get_user_lists()
            print(f"[SYNC LISTS TASK] Found {len(twitter_lists) if twitter_lists else 0} lists")
            
            if not twitter_lists:
                print(f"[SYNC LISTS TASK] No lists found")
                return
            
            # Close Playwright/Selenium before database operations to ensure clean sync context
            print(f"[SYNC LISTS TASK] Closing scraper...")
            lists_service.close()
            lists_service = None
            print(f"[SYNC LISTS TASK] Scraper closed")
        except Exception as e:
            print(f"[SYNC LISTS TASK] Error during list fetching: {e}")
            if lists_service:
                try:
                    lists_service.close()
                except:
                    pass
            raise
        
        # Wait a bit to ensure async context is cleared
        import time
        time.sleep(2)
        
        # Force close ALL database connections
        from django.db import connections
        connections.close_all()
        
        # Get fresh profile instance after connection reset
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Sync lists to database (now in clean sync context)
        synced_count = 0
        for list_data in twitter_lists:
            try:
                # Create a new service instance for database operations
                sync_service = ListsService(profile, use_playwright=False)
                sync_service.sync_list(
                    list_id=list_data['list_id'],
                    list_name=list_data['list_name'],
                    list_url=list_data.get('list_url')
                )
                synced_count += 1
            except Exception as e:
                print(f"[SYNC LISTS TASK] Error syncing list {list_data.get('list_id')}: {e}")
                continue
        
        print(f"[SYNC LISTS TASK] Synced {synced_count} list(s) successfully")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[SYNC LISTS TASK] EXCEPTION: {str(e)}")
        print(f"[SYNC LISTS TASK] TRACEBACK:\n{error_trace}")
        
        # Try to close scraper if it exists
        try:
            if lists_service:
                lists_service.close()
        except Exception as cleanup_error:
            print(f"[SYNC LISTS TASK] Error closing scraper in exception handler: {cleanup_error}")


@login_required
def list_selection(request):
    """Display list of available Twitter lists and allow selection with date filtering."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Get date filter (default to today) - US2
    from processing_app.utils import get_today_utc, get_date_navigation_context
    from lists_app.models import ListTweet
    
    date_str = request.GET.get('date', None)
    if date_str:
        try:
            filter_date = date.fromisoformat(date_str)
            # Validate future dates - show message if future date
            today_utc = get_today_utc()
            if filter_date > today_utc:
                messages.info(request, "No data available for future dates. Showing today's lists.")
                filter_date = today_utc
        except ValueError:
            filter_date = get_today_utc()
    else:
        filter_date = get_today_utc()
    
    # Get all lists for this user (sorted as on Twitter - maintain order)
    user_lists = TwitterList.objects.filter(
        twitter_profile=twitter_profile
    ).order_by('list_name')
    
    # Filter tweets within lists by creation date (or retweet date for retweets)
    # Lists themselves maintain Twitter sort order (per spec clarification)
    # Retweets are counted by the date they were retweeted, which is stored in created_at
    user_lists_with_counts = []
    for twitter_list in user_lists:
        # Filter tweets by creation date (created_at contains the date the tweet was created/retweeted)
        # This works for both regular tweets and retweets per spec clarification
        list_tweets = ListTweet.objects.filter(
            twitter_list=twitter_list,
            tweet__created_at__date=filter_date
        )
        
        tweet_count = list_tweets.count()
        
        user_lists_with_counts.append({
            'list': twitter_list,
            'tweet_count': tweet_count,
        })
    
    # Check if we need to fetch lists from Twitter
    if request.GET.get('sync') == 'true':
        try:
            import os
            # Default to Playwright if USE_PLAYWRIGHT env var is set (production)
            default_playwright = os.getenv('USE_PLAYWRIGHT', 'False').lower() == 'true'
            use_playwright = request.GET.get('use_playwright', str(default_playwright).lower()).lower() == 'true'
            
            # Run sync in a background thread to avoid async context issues
            thread = threading.Thread(
                target=_sync_lists_in_thread,
                args=(twitter_profile.id, use_playwright),
                daemon=False  # Don't make it a daemon so it completes
            )
            thread.start()
            
            # Return immediately - sync runs in background (no message, user can see status updates)
            return redirect('lists:list_selection')
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Error starting list sync: {error_details}")
            messages.error(request, f"Error starting list sync: {str(e)}")
    
    # Get date navigation context
    date_nav = get_date_navigation_context(request.user, filter_date)
    
    context = {
        'user_lists_with_counts': user_lists_with_counts,
        'user_lists': [item['list'] for item in user_lists_with_counts],  # For backward compatibility
        'twitter_profile': twitter_profile,
        'filter_date': filter_date,
        'date_nav': date_nav,
    }
    
    return render(request, 'lists/list_selection.html', context)


@login_required
def list_events(request, list_id):
    """Display events for a specific list with two-pane view."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.error(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    twitter_list = get_object_or_404(
        TwitterList,
        id=list_id,
        twitter_profile=twitter_profile
    )
    
    # Get date filter (default to today)
    from processing_app.utils import get_today_utc, get_date_navigation_context
    
    event_date_str = request.GET.get('date', None)
    if event_date_str:
        try:
            event_date = date.fromisoformat(event_date_str)
        except ValueError:
            event_date = get_today_utc()
    else:
        event_date = get_today_utc()
    
    # Get events for this date (Event model uses event_date)
    events = Event.objects.filter(
        twitter_list=twitter_list,
        event_date=event_date
    ).order_by('-tweet_count', '-created_at')
    
    # Get selected event
    selected_event_id = request.GET.get('event', None)
    selected_event = None
    if selected_event_id:
        try:
            selected_event = events.get(id=selected_event_id)
        except Event.DoesNotExist:
            pass
    
    # If no event selected, select the first one
    if not selected_event and events.exists():
        selected_event = events.first()
    
    # Get tweets for selected event
    event_tweets = []
    if selected_event:
        event_tweets = selected_event.event_tweets.select_related(
            'list_tweet__tweet'
        ).order_by('-relevance_score', '-list_tweet__tweet__created_at')
    
    # Get date navigation context
    date_nav = get_date_navigation_context(request.user, event_date)
    
    # Get processing status info
    from processing_app.utils import get_processing_status_info
    processing_status = get_processing_status_info(request.user, event_date)
    
    context = {
        'twitter_list': twitter_list,
        'events': events,
        'selected_event': selected_event,
        'event_tweets': event_tweets,
        'event_date': event_date,
        'twitter_profile': twitter_profile,
        'date_nav': date_nav,
        'processing_status': processing_status,
    }
    
    return render(request, 'lists/events.html', context)


def _sync_list_tweets_in_thread(list_id, profile_id, use_playwright, max_tweets=500):
    """
    DEPRECATED: This function is no longer used.
    List tweet syncing is now handled by processing_app processors via Django-Q.
    This function is kept for backward compatibility but should not be called.
    
    @deprecated Use processing_app.processors.ListProcessor instead
    """
    """Background task to sync list tweets - runs in a separate thread to avoid async context issues."""
    from django.db import connection
    
    # Close any existing database connections to avoid issues
    connection.close()
    
    lists_service = None
    try:
        print(f"[SYNC TWEETS TASK] Starting sync for list_id={list_id}, profile_id={profile_id}")
        
        # Get fresh instances in this thread
        profile = TwitterProfile.objects.get(id=profile_id)
        twitter_list = TwitterList.objects.get(id=list_id, twitter_profile=profile)
        
        # Initialize service
        lists_service = None
        try:
            lists_service = ListsService(profile, use_playwright=use_playwright)
            
            # Fetch tweets
            print(f"[SYNC TWEETS TASK] Fetching tweets from list...")
            tweets = lists_service.get_list_tweets(twitter_list, max_tweets=max_tweets)
            print(f"[SYNC TWEETS TASK] Found {len(tweets) if tweets else 0} tweets")
            
            # Close Playwright/Selenium before database operations to ensure clean sync context
            print(f"[SYNC TWEETS TASK] Closing scraper...")
            lists_service.close()
            lists_service = None
            print(f"[SYNC TWEETS TASK] Scraper closed")
        except Exception as e:
            print(f"[SYNC TWEETS TASK] Error during tweet fetching: {e}")
            if lists_service:
                try:
                    lists_service.close()
                except:
                    pass
            raise
        
        # Wait a bit to ensure async context is cleared
        import time
        time.sleep(2)
        
        # Force close ALL database connections
        from django.db import connections
        connections.close_all()
        
        # Get fresh instances after connection reset
        profile = TwitterProfile.objects.get(id=profile_id)
        twitter_list = TwitterList.objects.get(id=list_id, twitter_profile=profile)
        
        # Save tweets (now in clean sync context)
        seen_date = date.today()
        sync_service = ListsService(profile, use_playwright=False)
        saved_count = sync_service.save_list_tweets(twitter_list, tweets, seen_date=seen_date)
        
        print(f"[SYNC TWEETS TASK] Saved {saved_count} new tweets")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[SYNC TWEETS TASK] EXCEPTION: {str(e)}")
        print(f"[SYNC TWEETS TASK] TRACEBACK:\n{error_trace}")
        
        # Try to close scraper if it exists
        try:
            if lists_service:
                lists_service.close()
        except Exception as cleanup_error:
            print(f"[SYNC TWEETS TASK] Error closing scraper in exception handler: {cleanup_error}")


@login_required
def sync_list_tweets(request, list_id):
    """Get sync status for a Twitter list (read-only, no manual triggers)."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return JsonResponse({'error': 'Twitter profile not found'}, status=400)
    
    twitter_list = get_object_or_404(
        TwitterList,
        id=list_id,
        twitter_profile=twitter_profile
    )
    
    # Return status only - no manual sync triggers
    tweet_count = twitter_list.tweets.count()
    event_count = twitter_list.events.count()
    
    return JsonResponse({
        'success': True,
        'tweet_count': tweet_count,
        'event_count': event_count,
        'last_synced_at': twitter_list.last_synced_at.isoformat() if twitter_list.last_synced_at else None,
        'message': 'Content is processed automatically. No manual sync available.',
    })


def _generate_events_in_thread(list_id, profile_id, event_date):
    """Background task to generate events - runs in a separate thread."""
    from django.db import connection
    
    # Close any existing database connections
    connection.close()
    
    try:
        print(f"[GENERATE EVENTS TASK] Starting for list_id={list_id}, date={event_date}")
        
        # Get fresh instances
        profile = TwitterProfile.objects.get(id=profile_id)
        twitter_list = TwitterList.objects.get(id=list_id, twitter_profile=profile)
        
        # Generate events
        event_service = EventService(min_tweets_per_event=3, similarity_threshold=0.3)
        events = event_service.group_tweets_into_events(twitter_list, event_date)
        
        print(f"[GENERATE EVENTS TASK] Created {len(events)} events")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[GENERATE EVENTS TASK] EXCEPTION: {str(e)}")
        print(f"[GENERATE EVENTS TASK] TRACEBACK:\n{error_trace}")


@login_required
def generate_events(request, list_id):
    """Generate events from tweets for a specific list and date."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return JsonResponse({'error': 'Twitter profile not found'}, status=400)
    
    twitter_list = get_object_or_404(
        TwitterList,
        id=list_id,
        twitter_profile=twitter_profile
    )
    
    # Get date (default to today)
    event_date_str = request.GET.get('date', None)
    if event_date_str:
        try:
            event_date = date.fromisoformat(event_date_str)
        except ValueError:
            event_date = date.today()
    else:
        event_date = date.today()
    
    try:
        # Check if there are tweets to process
        tweet_count = twitter_list.tweets.filter(seen_date=event_date).count()
        if tweet_count == 0:
            return JsonResponse({
                'error': f'No tweets found for {event_date}. Please sync tweets first.',
            }, status=400)
        
        # Run in background thread for long-running operations
        thread = threading.Thread(
            target=_generate_events_in_thread,
            args=(list_id, twitter_profile.id, event_date),
            daemon=False
        )
        thread.start()
        
        # Return immediately - event generation runs in background
        return JsonResponse({
            'success': True,
            'message': f'Event generation started in the background for {tweet_count} tweets. Please refresh the page in a moment to see events.',
            'tweet_count': tweet_count,
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error generating events: {error_details}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def list_status(request, list_id):
    """Get status information for a list (tweet count, sync status, etc.)."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return JsonResponse({'error': 'Twitter profile not found'}, status=400)
    
    twitter_list = get_object_or_404(
        TwitterList,
        id=list_id,
        twitter_profile=twitter_profile
    )
    
    # Get tweet count
    tweet_count = twitter_list.tweets.count()
    event_count = twitter_list.events.count()
    
    # Check if sync is in progress (simplified - could be enhanced with task tracking)
    # For now, we'll just return the counts
    return JsonResponse({
        'tweet_count': tweet_count,
        'event_count': event_count,
        'last_synced_at': twitter_list.last_synced_at.isoformat() if twitter_list.last_synced_at else None,
        'syncing': False,  # Could be enhanced with actual task tracking
    })


@login_required
def delete_list(request, list_id):
    """Delete a Twitter list and all its associated data."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Twitter profile not found'}, status=400)
        messages.error(request, 'Twitter profile not found')
        return redirect('lists:list_selection')
    
    twitter_list = get_object_or_404(
        TwitterList,
        id=list_id,
        twitter_profile=twitter_profile
    )
    
    if request.method == 'POST':
        list_name = twitter_list.list_name
        
        # Get counts before deletion for the message
        tweet_count = twitter_list.tweets.count()
        event_count = twitter_list.events.count()
        
        # Delete the list (CASCADE will delete related tweets, events, etc.)
        with transaction.atomic():
            twitter_list.delete()
        
        success_message = (
            f"List '{list_name}' deleted successfully. "
            f"Removed {tweet_count} tweet(s) and {event_count} event(s)."
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_message
            })
        
        messages.success(request, success_message)
        return redirect('lists:list_selection')
    
    # GET request - return error
    messages.error(request, "Invalid request method")
    return redirect('lists:list_selection')


@login_required
def delete_all_lists(request):
    """Delete all Twitter lists for the current user."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Twitter profile not found'}, status=400)
        messages.error(request, 'Twitter profile not found')
        return redirect('lists:list_selection')
    
    if request.method == 'POST':
        # Get all lists for this user
        all_lists = TwitterList.objects.filter(twitter_profile=twitter_profile)
        list_count = all_lists.count()
        
        if list_count == 0:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'No lists to delete'}, status=400)
            messages.info(request, 'No lists to delete')
            return redirect('lists:list_selection')
        
        # Get counts before deletion
        total_tweets = sum(list_obj.tweets.count() for list_obj in all_lists)
        total_events = sum(list_obj.events.count() for list_obj in all_lists)
        
        # Delete all lists (CASCADE will delete related tweets, events, etc.)
        with transaction.atomic():
            all_lists.delete()
        
        success_message = (
            f"Deleted {list_count} list(s) successfully. "
            f"Removed {total_tweets} tweet(s) and {total_events} event(s)."
        )
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_message
            })
        
        messages.success(request, success_message)
        return redirect('lists:list_selection')
    
    # GET request - return error
    messages.error(request, "Invalid request method")
    return redirect('lists:list_selection')
