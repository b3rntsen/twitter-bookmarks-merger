"""
Django management command to export tweets from database to master/bookmarks.json format.

Usage:
    python manage.py export_to_master_json
"""
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from twitter.models import Tweet


class Command(BaseCommand):
    help = 'Export tweets from Django database to master/bookmarks.json format'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            help='Output file path (default: master/bookmarks.json)',
        )

    def handle(self, *args, **options):
        # Determine output path
        if options['output']:
            output_path = Path(options['output'])
        else:
            # Default: master/bookmarks.json relative to project root
            output_path = Path(__file__).parent.parent.parent.parent.parent / 'master' / 'bookmarks.json'

        self.stdout.write(f"Exporting tweets to: {output_path}")

        # Query all tweets ordered by created_at descending (newest first)
        tweets = Tweet.objects.all().order_by('-created_at')
        total = tweets.count()

        self.stdout.write(f"Found {total} tweets to export")

        # Convert to bookmarks.json format
        bookmarks = []
        for tweet in tweets:
            # Format Created At to Twitter format
            created_at = tweet.created_at.strftime('%a %b %d %H:%M:%S %z %Y')

            # Format Scraped At to ISO format
            if hasattr(tweet, 'scraped_at') and tweet.scraped_at:
                scraped_at = tweet.scraped_at.isoformat()
            else:
                scraped_at = datetime.now().isoformat()

            # Export media URLs and types
            media_urls = []
            media_types = []

            for media in tweet.media.all().order_by('created_at'):
                # Skip media with empty file_path
                if not media.file_path:
                    continue

                # Export as "local:filename" (compatible with bookmark_merger.py)
                media_urls.append(f"local:{Path(media.file_path).name}")

                # Map to XBookmarksExporter format
                if media.media_type == 'image':
                    media_types.append('photo')
                elif media.media_type == 'video':
                    media_types.append('video')
                else:
                    media_types.append(media.media_type)

            bookmark = {
                "Tweet Id": tweet.tweet_id,
                "Full Text": tweet.text_content,
                "Created At": created_at,
                "Scraped At": scraped_at,
                "Tweet URL": f"https://twitter.com/{tweet.author_username}/status/{tweet.tweet_id}",
                "User Screen Name": tweet.author_username,
                "User Name": tweet.author_display_name,
                "User Avatar Url": "",
                "User Description": "",
                "User Location": "",
                "User Followers Count": "",
                "User Is Blue Verified": "",
                "Retweet Count": str(tweet.retweet_count) if tweet.retweet_count else "",
                "Reply Count": str(tweet.reply_count) if tweet.reply_count else "",
                "Favorite Count": str(tweet.like_count) if tweet.like_count else "",
                "Media URLs": ", ".join(media_urls),
                "Media Types": ", ".join(media_types),
            }
            bookmarks.append(bookmark)

        # Write to JSON file
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(bookmarks, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(f"✓ Exported {len(bookmarks)} bookmarks to {output_path}"))
        self.stdout.write(f"File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
