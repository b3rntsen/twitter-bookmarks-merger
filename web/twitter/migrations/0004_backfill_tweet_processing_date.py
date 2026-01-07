# Generated manually on 2025-12-07 09:35

from django.db import migrations


def backfill_processing_date(apps, schema_editor):
    """Backfill processing_date from scraped_at date."""
    Tweet = apps.get_model('twitter', 'Tweet')
    for tweet in Tweet.objects.filter(processing_date__isnull=True):
        if tweet.scraped_at:
            tweet.processing_date = tweet.scraped_at.date()
            tweet.save(update_fields=['processing_date'])


def reverse_backfill(apps, schema_editor):
    """Reverse migration - set processing_date to None."""
    Tweet = apps.get_model('twitter', 'Tweet')
    Tweet.objects.update(processing_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ('twitter', '0003_tweet_processing_date'),
    ]

    operations = [
        migrations.RunPython(backfill_processing_date, reverse_backfill),
    ]

