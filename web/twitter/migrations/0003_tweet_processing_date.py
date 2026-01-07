# Generated manually on 2025-12-07 09:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('twitter', '0002_tweet_author_display_name_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tweet',
            name='processing_date',
            field=models.DateField(blank=True, db_index=True, help_text='Date when this tweet was processed/fetched', null=True),
        ),
        migrations.AddIndex(
            model_name='tweet',
            index=models.Index(fields=['processing_date'], name='twitter_twe_processing_date_idx'),
        ),
    ]

