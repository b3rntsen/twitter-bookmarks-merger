# Generated manually on 2025-12-07 09:35

from django.db import migrations


def backfill_processing_date(apps, schema_editor):
    """Backfill processing_date from created_at date."""
    CuratedFeed = apps.get_model('bookmarks_app', 'CuratedFeed')
    for feed in CuratedFeed.objects.filter(processing_date__isnull=True):
        if feed.created_at:
            feed.processing_date = feed.created_at.date()
            feed.save(update_fields=['processing_date'])


def reverse_backfill(apps, schema_editor):
    """Reverse migration - set processing_date to None."""
    CuratedFeed = apps.get_model('bookmarks_app', 'CuratedFeed')
    CuratedFeed.objects.update(processing_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ('bookmarks_app', '0002_curatedfeed_processing_date'),
    ]

    operations = [
        migrations.RunPython(backfill_processing_date, reverse_backfill),
    ]

