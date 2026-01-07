# Generated manually on 2025-12-07 09:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookmarks_app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='curatedfeed',
            name='processing_date',
            field=models.DateField(blank=True, db_index=True, help_text='Date when this curated feed was processed/fetched', null=True),
        ),
        migrations.AddIndex(
            model_name='curatedfeed',
            index=models.Index(fields=['processing_date'], name='bookmarks_a_processing_date_idx'),
        ),
    ]

