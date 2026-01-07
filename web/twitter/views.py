from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from .models import TwitterProfile
from .forms import TwitterConnectionForm
from .services import TwitterScraper, TwikitScraper
from bookmarks_app.services import BookmarkService
from django.conf import settings
from django.db import connection
from asgiref.sync import sync_to_async
import json
import os
# threading import kept for deprecated functions (not actively used)


@login_required
def connect_twitter(request):
    """Connect Twitter account."""
    existing_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if request.method == 'POST':
        form = TwitterConnectionForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data.get('password')
            use_cookies = form.cleaned_data.get('use_cookies', False)
            cookies_json = form.cleaned_data.get('cookies_json')
            
            # Parse cookies if provided
            cookies = None
            if use_cookies and cookies_json:
                try:
                    cookies = json.loads(cookies_json)
                except json.JSONDecodeError:
                    messages.error(request, "Invalid JSON format for cookies.")
                    return render(request, 'twitter/connect.html', {'form': form})
            
            # Create or update Twitter profile
            if existing_profile:
                profile = existing_profile
                profile.twitter_username = username
            else:
                profile = TwitterProfile(
                    user=request.user,
                    twitter_username=username
                )
            
            # Store encrypted credentials
            profile.set_credentials(username, password=password, cookies=cookies)
            profile.save()
            
            # Trigger immediate processing for new user connection
            from processing_app.schedulers import DailyScheduler
            scheduler = DailyScheduler()
            scheduler.schedule_user_jobs(user=request.user, immediate=True)
            
            messages.success(request, f"Twitter account @{username} connected successfully! Content processing has started.")
            return redirect('twitter:sync')
    else:
        form = TwitterConnectionForm()
        if existing_profile:
            form.fields['username'].initial = existing_profile.twitter_username
    
    return render(request, 'twitter/connect.html', {
        'form': form,
        'existing_profile': existing_profile
    })


@login_required
def disconnect_twitter(request):
    """Disconnect Twitter account."""
    profile = get_object_or_404(TwitterProfile, user=request.user)
    
    if request.method == 'POST':
        username = profile.twitter_username
        profile.delete()
        messages.success(request, f"Twitter account @{username} disconnected.")
        return redirect('twitter:connect')
    
    return render(request, 'twitter/disconnect.html', {'profile': profile})


def _sync_bookmarks_task(profile_id, max_bookmarks, use_playwright, use_twikit):
    """
    DEPRECATED: This function is no longer used.
    Bookmark syncing is now handled by processing_app processors via Django-Q.
    This function is kept for backward compatibility but should not be called.
    
    @deprecated Use processing_app.processors.BookmarkProcessor instead
    """
    """Background task to sync bookmarks - runs in a separate thread."""
    import traceback
    import sys
    from django.db import connection
    
    # Close any existing database connections to avoid issues
    connection.close()
    
    scraper = None
    try:
        print(f"[SYNC TASK] Starting sync for profile_id={profile_id}, max_bookmarks={max_bookmarks}")
        
        # Get fresh profile instance in this thread
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Update status to pending
        profile.sync_status = 'pending'
        profile.sync_error_message = ''
        profile.save()
        print(f"[SYNC TASK] Profile status set to pending")
        
        # Get credentials
        credentials = profile.get_credentials()
        if not credentials:
            error_msg = 'Credentials decryption failed - encryption key mismatch'
            print(f"[SYNC TASK] ERROR: {error_msg}")
            profile.sync_status = 'error'
            profile.sync_error_message = error_msg
            profile.save()
            return
        
        print(f"[SYNC TASK] Credentials retrieved for user: {credentials.get('username')}")
        
        # Initialize scraper
        if use_twikit:
            print(f"[SYNC TASK] Initializing TwikitScraper...")
            scraper = TwikitScraper(
                username=credentials.get('username'),
                password=credentials.get('password'),
                cookies=credentials.get('cookies')
            )
        else:
            print(f"[SYNC TASK] Initializing TwitterScraper (playwright={use_playwright})...")
            scraper = TwitterScraper(
                username=credentials.get('username'),
                password=credentials.get('password'),
                cookies=credentials.get('cookies'),
                use_playwright=use_playwright
            )
        
        # Login
        print(f"[SYNC TASK] Attempting to login to Twitter as {credentials.get('username')}...")
        login_success = scraper.login()
        print(f"[SYNC TASK] Login result: {login_success}")
        
        if not login_success:
            raise Exception(
                "Failed to login to Twitter. This could be due to:\n"
                "- Incorrect username or password\n"
                "- Twitter requiring additional verification (captcha, phone verification)\n"
                "- Twitter blocking automated logins\n"
                "- Twitter's login page structure changed\n\n"
                "Check the server logs for detailed error messages. "
                "You may want to try using session cookies instead of password."
            )
        
        # Get bookmarks
        print(f"[SYNC TASK] Fetching bookmarks (max={max_bookmarks})...")
        bookmarks = scraper.get_bookmarks(max_bookmarks=max_bookmarks)
        print(f"[SYNC TASK] Found {len(bookmarks) if bookmarks else 0} bookmarks")
        
        if not bookmarks:
            print(f"[SYNC TASK] No bookmarks found, marking as success")
            profile.sync_status = 'success'
            profile.last_sync_at = timezone.now()
            profile.save()
            scraper.close()
            return
        
        # Store bookmarks
        print(f"[SYNC TASK] Storing {len(bookmarks)} bookmarks...")
        bookmark_service = BookmarkService(profile)
        stored_count = bookmark_service.store_bookmarks(bookmarks)
        print(f"[SYNC TASK] Stored {stored_count} bookmarks")
        
        # Update profile
        profile.sync_status = 'success'
        profile.last_sync_at = timezone.now()
        profile.sync_error_message = ''
        profile.save()
        print(f"[SYNC TASK] Sync completed successfully")
        
        # Close scraper
        scraper.close()
        print(f"[SYNC TASK] Scraper closed")
        
    except Exception as e:
        # Log full traceback
        error_trace = traceback.format_exc()
        print(f"[SYNC TASK] EXCEPTION: {str(e)}")
        print(f"[SYNC TASK] TRACEBACK:\n{error_trace}")
        sys.stderr.write(f"[SYNC TASK] ERROR: {str(e)}\n{traceback.format_exc()}\n")
        
        # Update profile with error
        try:
            profile = TwitterProfile.objects.get(id=profile_id)
            profile.sync_status = 'error'
            # Truncate error message if too long
            error_msg = str(e)
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "... (truncated)"
            profile.sync_error_message = error_msg
            profile.save()
            print(f"[SYNC TASK] Error saved to profile")
        except Exception as save_error:
            print(f"[SYNC TASK] Failed to save error to profile: {save_error}")
        
        # Try to close scraper if it exists
        try:
            if scraper:
                scraper.close()
                print(f"[SYNC TASK] Scraper closed after error")
        except Exception as close_error:
            print(f"[SYNC TASK] Error closing scraper: {close_error}")


def _run_sync_in_thread(profile_id, max_bookmarks, use_playwright, use_twikit):
    """
    DEPRECATED: This function is no longer used.
    Bookmark syncing is now handled by processing_app processors via Django-Q.
    This function is kept for backward compatibility but should not be called.
    
    @deprecated Use processing_app.processors.BookmarkProcessor instead
    """
    """Run sync in a separate thread to avoid async context issues."""
    from django.db import connection
    import traceback
    
    # Close any existing database connections
    connection.close()
    
    scraper = None
    try:
        # Get fresh profile instance
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Update status to pending
        profile.sync_status = 'pending'
        profile.sync_error_message = ''
        profile.save()
        
        # Get credentials
        credentials = profile.get_credentials()
        if not credentials:
            profile.sync_status = 'error'
            profile.sync_error_message = 'Credentials decryption failed - encryption key mismatch'
            profile.save()
            return
        
        # Initialize scraper
        if use_twikit:
            scraper = TwikitScraper(
                username=credentials.get('username'),
                password=credentials.get('password'),
                cookies=credentials.get('cookies')
            )
        else:
            scraper = TwitterScraper(
                username=credentials.get('username'),
                password=credentials.get('password'),
                cookies=credentials.get('cookies'),
                use_playwright=use_playwright
            )
        
        # Login
        print(f"Attempting to login to Twitter as {credentials.get('username')}...")
        login_success = scraper.login()
        if not login_success:
            raise Exception(
                "Failed to login to Twitter. This could be due to:\n"
                "- Incorrect username or password\n"
                "- Twitter requiring additional verification (captcha, phone verification)\n"
                "- Twitter blocking automated logins\n"
                "- Twitter's login page structure changed\n\n"
                "Check the server logs for detailed error messages. "
                "You may want to try using session cookies instead of password."
            )
        
        # Get bookmarks
        print(f"Fetching bookmarks (max={max_bookmarks})...")
        bookmarks = scraper.get_bookmarks(max_bookmarks=max_bookmarks)
        print(f"Found {len(bookmarks) if bookmarks else 0} bookmarks")
        
        if not bookmarks:
            # Close scraper first
            scraper.close()
            scraper = None
            
            # Close and reopen database connection
            from django.db import connection
            connection.close()
            
            profile.sync_status = 'success'
            profile.last_sync_at = timezone.now()
            profile.save()
            return
        
        # Close scraper completely FIRST, before any database operations
        scraper.close()
        scraper = None
        
        # Wait to ensure Playwright's async context is fully cleared
        import time
        time.sleep(3)  # Longer delay to ensure async context is cleared
        
        # Force close ALL database connections
        from django.db import connections
        connections.close_all()
        
        # Additional wait after closing connections
        time.sleep(1)
        
        # Get fresh profile instance after connection reset
        # This ensures we're using a new connection in a clean sync context
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Store bookmarks (now in clean sync context)
        print(f"Storing {len(bookmarks)} bookmarks...")
        bookmark_service = BookmarkService(profile)
        stored_count = bookmark_service.store_bookmarks(bookmarks)
        print(f"Stored {stored_count} bookmarks")
        
        # Update profile
        profile.sync_status = 'success'
        profile.last_sync_at = timezone.now()
        profile.sync_error_message = ''
        profile.save()
        
        print("Sync completed successfully")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"SYNC ERROR: {str(e)}")
        print(f"TRACEBACK:\n{error_trace}")
        
        # Update profile with error
        try:
            profile = TwitterProfile.objects.get(id=profile_id)
            profile.sync_status = 'error'
            error_msg = str(e)
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "... (truncated)"
            profile.sync_error_message = error_msg
            profile.save()
        except:
            pass
        
        # Try to close scraper
        try:
            if scraper:
                scraper.close()
        except:
            pass


@login_required
def sync_bookmarks(request):
    """Trigger bookmark synchronization."""
    profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not profile:
        messages.warning(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Show status only - no manual triggers (content is processed automatically)
    return render(request, 'twitter/sync.html', {'profile': profile})

