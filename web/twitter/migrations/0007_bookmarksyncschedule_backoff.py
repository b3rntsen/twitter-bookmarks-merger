from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('twitter', '0006_bookmarksyncschedule_bookmarksyncjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookmarksyncschedule',
            name='backoff_multiplier',
            field=models.IntegerField(default=1, help_text='Multiplier for interval on transient failures (1-12)'),
        ),
        migrations.AddField(
            model_name='bookmarksyncschedule',
            name='last_error_type',
            field=models.CharField(blank=True, help_text='Type of last error (e.g. cookie_expired, timeout)', max_length=50),
        ),
    ]
