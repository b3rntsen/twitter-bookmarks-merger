# Generated manually on 2025-12-07 09:35

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from datetime import time


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('twitter', '0002_tweet_author_display_name_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentProcessingJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_type', models.CharField(choices=[('bookmarks', 'Bookmarks'), ('curated_feed', 'Curated Feed'), ('lists', 'Lists')], max_length=20)),
                ('processing_date', models.DateField(db_index=True, help_text='Date for which content is being processed')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed'), ('retrying', 'Retrying')], db_index=True, default='pending', max_length=20)),
                ('retry_count', models.IntegerField(default=0, help_text='Number of retry attempts')),
                ('max_retries', models.IntegerField(default=5, help_text='Maximum retry attempts')),
                ('scheduled_at', models.DateTimeField(help_text='When the job was scheduled to run')),
                ('started_at', models.DateTimeField(blank=True, help_text='When the job started processing', null=True)),
                ('completed_at', models.DateTimeField(blank=True, help_text='When the job completed', null=True)),
                ('next_retry_at', models.DateTimeField(blank=True, help_text='When to retry if failed', null=True)),
                ('items_processed', models.IntegerField(default=0, help_text='Number of items (tweets, etc.) processed')),
                ('error_message', models.TextField(blank=True, help_text='Error message if job failed')),
                ('error_traceback', models.TextField(blank=True, help_text='Full traceback if job failed')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('twitter_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='processing_jobs', to='twitter.twitterprofile')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='processing_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-processing_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ProcessingSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('processing_time', models.TimeField(default=time(2, 0), help_text='UTC time for daily processing')),
                ('timezone', models.CharField(default='UTC', help_text="User's timezone (for display)", max_length=50)),
                ('enabled', models.BooleanField(default=True, help_text='Whether automatic processing is enabled')),
                ('process_bookmarks', models.BooleanField(default=True)),
                ('process_curated_feed', models.BooleanField(default=True)),
                ('process_lists', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='processing_schedule', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['user'],
            },
        ),
        migrations.CreateModel(
            name='DailyContentSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('processing_date', models.DateField(db_index=True)),
                ('bookmark_count', models.IntegerField(default=0)),
                ('curated_feed_count', models.IntegerField(default=0)),
                ('list_count', models.IntegerField(default=0)),
                ('total_tweet_count', models.IntegerField(default=0)),
                ('all_jobs_completed', models.BooleanField(default=False, help_text='True if all content types processed successfully')),
                ('last_processed_at', models.DateTimeField(blank=True, help_text='When last job completed', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('twitter_profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_snapshots', to='twitter.twitterprofile')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_snapshots', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-processing_date'],
            },
        ),
        migrations.AddIndex(
            model_name='contentprocessingjob',
            index=models.Index(fields=['user', 'processing_date', 'content_type'], name='processing__user_id_processing_date_content_type_idx'),
        ),
        migrations.AddIndex(
            model_name='contentprocessingjob',
            index=models.Index(fields=['status', 'next_retry_at'], name='processing__status_next_retry_at_idx'),
        ),
        migrations.AddIndex(
            model_name='contentprocessingjob',
            index=models.Index(fields=['twitter_profile', 'content_type', 'processing_date'], name='processing__twitter_profile_content_type_processing_date_idx'),
        ),
        migrations.AddIndex(
            model_name='dailycontentsnapshot',
            index=models.Index(fields=['user', 'processing_date'], name='processing__user_id_processing_date_idx'),
        ),
        migrations.AddIndex(
            model_name='dailycontentsnapshot',
            index=models.Index(fields=['twitter_profile', 'processing_date'], name='processing__twitter_profile_processing_date_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='contentprocessingjob',
            unique_together={('user', 'twitter_profile', 'content_type', 'processing_date')},
        ),
        migrations.AlterUniqueTogether(
            name='dailycontentsnapshot',
            unique_together={('user', 'twitter_profile', 'processing_date')},
        ),
    ]

