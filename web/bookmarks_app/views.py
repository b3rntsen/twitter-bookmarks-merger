from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, FileResponse, Http404
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
from django.urls import reverse
from datetime import datetime, date
import os
# threading import removed - no longer used (deprecated functions use it but are not called)
from twitter.models import Tweet, TwitterProfile
from twitter.services import TwitterScraper
from accounts.models import UserProfile
from bookmarks_app.pdf_generator import PDFGenerator
from bookmarks_app.models import CuratedFeed, TweetCategory, CategorizedTweet
from bookmarks_app.categorization_service import TweetCategorizationService
from bookmarks_app.services import BookmarkService


@login_required
def bookmark_list(request):
    """Display list of bookmarks."""
    from processing_app.utils import get_today_utc, get_date_navigation_context
    
    # Get user's Twitter profile
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return redirect('twitter:connect')
    
    # Get date filter (default to today)
    date_str = request.GET.get('date', None)
    if date_str:
        try:
            filter_date = date.fromisoformat(date_str)
        except ValueError:
            filter_date = get_today_utc()
    else:
        filter_date = get_today_utc()
    
    # Get bookmarks filtered by processing_date
    bookmarks = Tweet.objects.filter(
        twitter_profile=twitter_profile,
        is_bookmark=True,
        processing_date=filter_date
    ).order_by('-created_at')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        bookmarks = bookmarks.filter(
            Q(text_content__icontains=search_query) |
            Q(author_username__icontains=search_query)
        )
    
    # Filter by author
    author_filter = request.GET.get('author', '')
    if author_filter:
        bookmarks = bookmarks.filter(author_username=author_filter)
    
    # Pagination
    paginator = Paginator(bookmarks, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get unique authors for filter - return both username and display name
    # We'll show display name but filter by username
    authors_data = Tweet.objects.filter(
        twitter_profile=twitter_profile,
        is_bookmark=True
    ).exclude(
        author_username=''
    ).values('author_username', 'author_display_name').distinct().order_by('author_display_name', 'author_username')
    
    # Create list of dicts for the filter (easier to use in template)
    authors = [
        {
            'username': item['author_username'],
            'display_name': item.get('author_display_name') or item['author_username']
        }
        for item in authors_data
    ]
    
    # Get date navigation context
    date_nav = get_date_navigation_context(request.user, filter_date)
    
    # Get processing status info
    from processing_app.utils import get_processing_status_info
    processing_status = get_processing_status_info(request.user, filter_date)
    
    context = {
        'page_obj': page_obj,
        'bookmarks': page_obj,
        'search_query': search_query,
        'author_filter': author_filter,
        'authors': authors,
        'twitter_profile': twitter_profile,
        'filter_date': filter_date,
        'date_nav': date_nav,
        'processing_status': processing_status,
        'MEDIA_URL': settings.MEDIA_URL,
    }
    
    return render(request, 'bookmarks/list.html', context)


@login_required
def bookmark_detail(request, tweet_id):
    """Display individual bookmark with thread."""
    bookmark = get_object_or_404(
        Tweet,
        tweet_id=tweet_id,
        twitter_profile__user=request.user,
        is_bookmark=True
    )
    
    # Get thread tweets - only if this is part of a thread from the same author
    thread_tweets = []
    has_thread = False
    if bookmark.conversation_id:
        # Get all tweets in the conversation from the same author
        conversation_tweets = Tweet.objects.filter(
            conversation_id=bookmark.conversation_id,
            twitter_profile=bookmark.twitter_profile,
            author_username=bookmark.author_username
        ).order_by('thread_position', 'created_at')
        
        # Only show thread if there's more than one tweet from this author
        if conversation_tweets.count() > 1:
            thread_tweets = list(conversation_tweets)
            has_thread = True
    
    # Get media
    media = bookmark.media.all()
    
    # Get replies
    replies = bookmark.replies.all().order_by('created_at')
    
    context = {
        'bookmark': bookmark,
        'thread_tweets': thread_tweets,
        'has_thread': has_thread,
        'media': media,
        'replies': replies,
        'MEDIA_URL': settings.MEDIA_URL,
    }
    
    return render(request, 'bookmarks/detail.html', context)


@login_required
def delete_bookmark(request, tweet_id):
    """Delete a bookmark."""
    bookmark = get_object_or_404(
        Tweet,
        tweet_id=tweet_id,
        twitter_profile__user=request.user,
        is_bookmark=True
    )
    
    if request.method == 'POST':
        # Delete associated media files
        for media in bookmark.media.all():
            try:
                import os
                from django.conf import settings
                if media.file_path:
                    file_path = os.path.join(settings.MEDIA_ROOT, media.file_path)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                if media.thumbnail_path:
                    thumb_path = os.path.join(settings.MEDIA_ROOT, media.thumbnail_path)
                    if os.path.exists(thumb_path):
                        os.remove(thumb_path)
            except Exception as e:
                print(f"Error deleting media file: {e}")
        
        # Delete the bookmark (this will cascade delete media, threads, etc.)
        bookmark.delete()
        
        from django.contrib import messages
        messages.success(request, 'Bookmark deleted successfully.')
        return redirect('bookmark_list')
    
    # GET request - show confirmation
    context = {
        'bookmark': bookmark,
    }
    return render(request, 'bookmarks/delete_confirm.html', context)


@login_required
def delete_all_bookmarks(request):
    """Delete all bookmarks for the user."""
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        return redirect('twitter:connect')
    
    if request.method == 'POST':
        # Get all bookmarks
        bookmarks = Tweet.objects.filter(
            twitter_profile=twitter_profile,
            is_bookmark=True
        )
        
        count = bookmarks.count()
        
        # Delete associated media files
        for bookmark in bookmarks:
            for media in bookmark.media.all():
                try:
                    import os
                    from django.conf import settings
                    if media.file_path:
                        file_path = os.path.join(settings.MEDIA_ROOT, media.file_path)
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    if media.thumbnail_path:
                        thumb_path = os.path.join(settings.MEDIA_ROOT, media.thumbnail_path)
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)
                except Exception as e:
                    print(f"Error deleting media file: {e}")
        
        # Delete all bookmarks
        bookmarks.delete()
        
        from django.contrib import messages
        messages.success(request, f'Deleted {count} bookmark(s) successfully.')
        return redirect('bookmark_list')
    
    # GET request - show confirmation
    context = {
        'bookmark_count': Tweet.objects.filter(
            twitter_profile=twitter_profile,
            is_bookmark=True
        ).count(),
    }
    return render(request, 'bookmarks/delete_all_confirm.html', context)


@login_required
def preview_pdf(request, tweet_id):
    """Generate and preview PDF for a bookmark in browser."""
    bookmark = get_object_or_404(
        Tweet,
        tweet_id=tweet_id,
        twitter_profile__user=request.user,
        is_bookmark=True
    )
    
    # Get thread tweets
    thread_tweets = []
    if bookmark.conversation_id:
        thread_tweets = Tweet.objects.filter(
            conversation_id=bookmark.conversation_id,
            twitter_profile=bookmark.twitter_profile
        ).order_by('thread_position', 'created_at')
    
    # Generate PDF
    pdf_generator = PDFGenerator()
    pdf_file = pdf_generator.generate_pdf(bookmark, thread_tweets)
    
    # Return as inline (preview in browser) with proper headers
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="bookmark_{tweet_id}.pdf"'
    response['Content-Length'] = len(pdf_file)
    # Allow iframe embedding
    response['X-Content-Type-Options'] = 'nosniff'
    
    return response


@login_required
def download_pdf(request, tweet_id):
    """Generate and download PDF for a bookmark."""
    bookmark = get_object_or_404(
        Tweet,
        tweet_id=tweet_id,
        twitter_profile__user=request.user,
        is_bookmark=True
    )
    
    # Get thread tweets
    thread_tweets = []
    if bookmark.conversation_id:
        thread_tweets = Tweet.objects.filter(
            conversation_id=bookmark.conversation_id,
            twitter_profile=bookmark.twitter_profile
        ).order_by('thread_position', 'created_at')
    
    # Generate PDF
    pdf_generator = PDFGenerator()
    pdf_file = pdf_generator.generate_pdf(bookmark, thread_tweets)
    
    # Return as download
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="bookmark_{tweet_id}.pdf"'
    
    return response


@login_required
def view_html(request, tweet_id):
    """View sanitized HTML content of a bookmark."""
    bookmark = get_object_or_404(
        Tweet,
        tweet_id=tweet_id,
        twitter_profile__user=request.user,
        is_bookmark=True
    )
    
    if not bookmark.html_content_sanitized:
        from django.contrib import messages
        messages.warning(request, 'HTML content not available for this bookmark. It may need to be re-synced.')
        return redirect('bookmark_detail', tweet_id=tweet_id)
    
    context = {
        'bookmark': bookmark,
        'html_content': bookmark.html_content_sanitized,
        'MEDIA_URL': settings.MEDIA_URL,
    }
    
    return render(request, 'bookmarks/view_html.html', context)


@login_required
def curated_feed(request):
    """Display curated feed with categorized tweets."""
    from processing_app.utils import get_today_utc, get_date_navigation_context
    
    twitter_profile = TwitterProfile.objects.filter(user=request.user).first()
    
    if not twitter_profile:
        messages.warning(request, "Please connect your Twitter account first.")
        return redirect('twitter:connect')
    
    # Get date filter (default to today)
    date_str = request.GET.get('date', None)
    if date_str:
        try:
            filter_date = date.fromisoformat(date_str)
        except ValueError:
            filter_date = get_today_utc()
    else:
        filter_date = get_today_utc()
    
    # Get curated feed for the specified date
    latest_feed = CuratedFeed.objects.filter(
        user=request.user,
        twitter_profile=twitter_profile,
        processing_date=filter_date
    ).first()
    
    # If this is a polling request (check parameter), return minimal response
    if request.GET.get('check'):
        from django.http import JsonResponse
        return JsonResponse({
            'has_feed': latest_feed is not None,
            'has_categories': latest_feed and latest_feed.categories.exists() if latest_feed else False,
            'feed_id': latest_feed.id if latest_feed else None
        })
    
    # Get categories with their tweets
    categories_data = []
    if latest_feed:
        categories = TweetCategory.objects.filter(curated_feed=latest_feed).order_by('name')
        for category in categories:
            categorized_tweets = CategorizedTweet.objects.filter(
                category=category
            ).select_related('tweet').order_by('-tweet__created_at')
            
            tweets = [ct.tweet for ct in categorized_tweets]
            categories_data.append({
                'category': category,
                'tweets': tweets,
                'summary': category.summary,
            })
    
    # Get date navigation context
    date_nav = get_date_navigation_context(request.user, filter_date)
    
    # Get processing status info
    from processing_app.utils import get_processing_status_info
    processing_status = get_processing_status_info(request.user, filter_date)
    
    context = {
        'latest_feed': latest_feed,
        'categories_data': categories_data,
        'twitter_profile': twitter_profile,
        'filter_date': filter_date,
        'date_nav': date_nav,
        'processing_status': processing_status,
        'MEDIA_URL': settings.MEDIA_URL,
    }
    
    return render(request, 'bookmarks/curated_feed.html', context)


def _fetch_and_categorize_tweets_task(profile_id, num_tweets, use_playwright):
    """
    DEPRECATED: This function is no longer used.
    Content fetching is now handled by processing_app processors via Django-Q.
    This function is kept for backward compatibility but should not be called.
    
    @deprecated Use processing_app.processors.CuratedFeedProcessor instead
    """
    """Background task to fetch and categorize tweets."""
    import traceback
    from django.db import connection
    
    # Close any existing database connections
    connection.close()
    
    scraper = None
    try:
        print(f"[CURATED FEED TASK] Starting fetch for profile_id={profile_id}, num_tweets={num_tweets}")
        
        # Get fresh profile instance
        profile = TwitterProfile.objects.get(id=profile_id)
        user = profile.user
        
        # Get user's AI provider preference
        user_profile, _ = UserProfile.objects.get_or_create(user=user)
        # Use getattr to handle case where field doesn't exist yet (migration pending)
        ai_provider = getattr(user_profile, 'ai_provider', None) or 'anthropic'
        print(f"[CURATED FEED TASK] Using AI provider: {ai_provider}")
        
        # Get credentials
        credentials = profile.get_credentials()
        if not credentials:
            print(f"[CURATED FEED TASK] ERROR: Could not decrypt credentials")
            return
        
        # Initialize scraper
        scraper = TwitterScraper(
            username=credentials.get('username'),
            password=credentials.get('password'),
            cookies=credentials.get('cookies'),
            use_playwright=use_playwright
        )
        
        # Fetch tweets from home timeline
        print(f"[CURATED FEED TASK] Fetching {num_tweets} tweets from home timeline...")
        tweets_data = scraper.get_home_timeline(max_tweets=num_tweets)
        print(f"[CURATED FEED TASK] Fetched {len(tweets_data)} tweets")
        
        if not tweets_data:
            print(f"[CURATED FEED TASK] No tweets fetched")
            scraper.close()
            scraper = None
            return
        
        # Close scraper before database operations to avoid async context issues
        scraper.close()
        scraper = None
        
        # Force close all database connections and ensure clean sync context
        from django.db import connections
        connections.close_all()
        
        # Wait to ensure Playwright's async context is fully cleared
        import time
        time.sleep(2)
        
        # Get fresh profile instance after connection reset
        profile = TwitterProfile.objects.get(id=profile_id)
        
        # Store tweets in database (similar to bookmarks)
        bookmark_service = BookmarkService(profile)
        stored_tweets = []
        
        for tweet_data in tweets_data:
            # Parse timestamp
            created_at = bookmark_service._parse_timestamp(tweet_data.get('created_at'))
            
            # Get or create tweet
            tweet, created = Tweet.objects.get_or_create(
                tweet_id=tweet_data['tweet_id'],
                defaults={
                    'twitter_profile': profile,
                    'author_username': tweet_data.get('author_username', ''),
                    'author_display_name': tweet_data.get('author_display_name', ''),
                    'author_profile_image_url': tweet_data.get('author_profile_image_url', ''),
                    'text_content': tweet_data.get('text_content', ''),
                    'created_at': created_at,
                    'like_count': tweet_data.get('like_count', 0),
                    'retweet_count': tweet_data.get('retweet_count', 0),
                    'reply_count': tweet_data.get('reply_count', 0),
                    'is_bookmark': False,  # These are not bookmarks
                    'raw_data': tweet_data,
                }
            )
            stored_tweets.append(tweet)
        
        print(f"[CURATED FEED TASK] Stored {len(stored_tweets)} tweets in database")
        
        # Categorize tweets
        print(f"[CURATED FEED TASK] Categorizing tweets using {ai_provider}...")
        try:
            categorization_service = TweetCategorizationService(provider=ai_provider)
            categorized = categorization_service.categorize_tweets(tweets_data)
            print(f"[CURATED FEED TASK] Created {len(categorized)} categories")
        except ValueError as e:
            print(f"[CURATED FEED TASK] ERROR: {e}")
            # Fallback: create a single "Uncategorized" category
            categorized = {
                "Uncategorized": {
                    'description': f'Tweets that could not be categorized ({ai_provider} API key may be missing)',
                    'tweets': tweets_data
                }
            }
            print(f"[CURATED FEED TASK] Using fallback categorization")
        
        # Create CuratedFeed record
        curated_feed = CuratedFeed.objects.create(
            user=user,
            twitter_profile=profile,
            num_tweets_fetched=len(stored_tweets),
            num_categories=len(categorized),
            config_num_tweets=num_tweets,
        )
        
        # Create categories and link tweets
        for category_name, category_info in categorized.items():
            category_tweets = category_info.get('tweets', [])
            if not category_tweets:
                continue
            
            # Generate summary using the same provider
            try:
                summary = categorization_service.summarize_category(category_name, category_tweets)
            except Exception as e:
                print(f"[CURATED FEED TASK] Error generating summary for {category_name}: {e}")
                # Fallback summary
                authors = set()
                for tweet_data in category_tweets:
                    author = tweet_data.get('author_username', 'unknown')
                    display_name = tweet_data.get('author_display_name', author)
                    authors.add(f"@{author} ({display_name})")
                summary = f"This category contains {len(category_tweets)} tweets from {len(authors)} authors: {', '.join(sorted(authors))}."
            
            # Create category
            tweet_category = TweetCategory.objects.create(
                curated_feed=curated_feed,
                name=category_name,
                description=category_info.get('description', ''),
                summary=summary,
            )
            
            # Link tweets to category
            for tweet_data in category_tweets:
                tweet_id = tweet_data.get('tweet_id')
                if tweet_id:
                    tweet = Tweet.objects.filter(tweet_id=tweet_id).first()
                    if tweet:
                        CategorizedTweet.objects.get_or_create(
                            category=tweet_category,
                            tweet=tweet,
                        )
        
        print(f"[CURATED FEED TASK] Completed successfully")
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"[CURATED FEED TASK] EXCEPTION: {str(e)}")
        print(f"[CURATED FEED TASK] TRACEBACK:\n{error_trace}")
    finally:
        # Ensure scraper is ALWAYS closed, even on exceptions
        print(f"[CURATED FEED TASK] Cleaning up scraper...")
        try:
            if scraper:
                print(f"[CURATED FEED TASK] Closing scraper...")
                scraper.close()
                scraper = None
                print(f"[CURATED FEED TASK] Scraper closed")
        except Exception as e:
            print(f"[CURATED FEED TASK] Error closing scraper in finally: {e}")
            import traceback
            traceback.print_exc()
        
        # Force cleanup of database connections
        try:
            from django.db import connections
            connections.close_all()
        except Exception as e:
            print(f"[CURATED FEED TASK] Error closing DB connections: {e}")
        
        print(f"[CURATED FEED TASK] Cleanup complete")


@login_required
def fetch_curated_feed(request):
    """
    DEPRECATED: Manual fetch endpoint removed.
    Content is now processed automatically via Django-Q.
    Returns 404 to indicate endpoint is no longer available.
    """
    from django.http import Http404
    raise Http404("Manual fetch endpoint has been removed. Content is processed automatically.")


@login_required
def serve_video(request, tweet_id: str, filename: str):
    """
    Serve video file with authentication check.
    
    Verifies user has access to the bookmark before serving video.
    
    Args:
        request: Django HttpRequest
        tweet_id: Tweet ID
        filename: Video filename (e.g., 'video_1.mp4')
        
    Returns:
        FileResponse with video file, or 404 if not found/unauthorized
    """
    # Verify user has access to tweet
    if not _user_has_access_to_tweet(request.user, tweet_id):
        raise Http404("Video not found or access denied")
    
    # Construct file path
    file_path = os.path.join(settings.MEDIA_ROOT, 'tweets', tweet_id, filename)
    
    # Verify file exists
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise Http404("Video file not found")
    
    # Determine content type from file extension
    ext = os.path.splitext(filename)[1].lower()
    content_types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.ogg': 'video/ogg',
        '.ogv': 'video/ogg',
        '.m4v': 'video/mp4',
        '.mov': 'video/quicktime',
    }
    content_type = content_types.get(ext, 'video/mp4')
    
    # Serve file
    return FileResponse(open(file_path, 'rb'), content_type=content_type)


def _user_has_access_to_tweet(user, tweet_id: str) -> bool:
    """
    Check if user has access to tweet (owns the TwitterProfile).
    
    Args:
        user: Django User instance
        tweet_id: Tweet ID to check
        
    Returns:
        True if user has access, False otherwise
    """
    try:
        tweet = Tweet.objects.get(tweet_id=tweet_id)
        # Verify tweet belongs to user's TwitterProfile
        twitter_profile = TwitterProfile.objects.filter(user=user).first()
        if not twitter_profile:
            return False
        return tweet.twitter_profile == twitter_profile
    except Tweet.DoesNotExist:
        return False

