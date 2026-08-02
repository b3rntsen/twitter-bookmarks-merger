"""Admin smoke tests for the watermark fields.

The schedule admin gained computed columns (``watermark_display``,
``next_fetch_display``) and an action. Those only fail at render time, so the
changelist and change form are exercised here rather than trusted.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from twitter.models import BookmarkSyncSchedule, TwitterProfile


class ScheduleAdminSmokeTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.client.force_login(self.admin)
        profile = TwitterProfile.objects.create(
            user=self.admin, twitter_username='tester', encrypted_credentials='')
        self.schedule = BookmarkSyncSchedule.objects.create(
            twitter_profile=profile, use_until_synced=True)

    def test_changelist_renders_without_a_watermark(self):
        response = self.client.get(reverse('admin:twitter_bookmarksyncschedule_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not established')

    def test_changelist_renders_with_a_watermark(self):
        self.schedule.verified_ok_before = timezone.now()
        self.schedule.verified_count = 4579
        self.schedule.verification_report = {'fetch_gap_count': 2}
        self.schedule.save()

        response = self.client.get(reverse('admin:twitter_bookmarksyncschedule_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '4579 verified')
        self.assertContains(response, '2 gaps')

    def test_change_form_renders_the_next_fetch_plan(self):
        # next_fetch_display calls plan_fetch, which hits the DB and the stored
        # report — a readonly field that raises would 500 the whole form.
        url = reverse('admin:twitter_bookmarksyncschedule_change', args=[self.schedule.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'birdmarks --rebuild')
        self.assertContains(response, 'Verified Completeness')

    def test_change_form_renders_when_bounded(self):
        self.schedule.verified_ok_before = timezone.now()
        self.schedule.last_full_rebuild_at = timezone.now()
        self.schedule.verification_report = {}
        self.schedule.save()
        url = reverse('admin:twitter_bookmarksyncschedule_change', args=[self.schedule.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '--max-pages')

    def test_add_form_renders(self):
        # next_fetch_display must tolerate an unsaved object (pk is None).
        response = self.client.get(reverse('admin:twitter_bookmarksyncschedule_add'))

        self.assertEqual(response.status_code, 200)
