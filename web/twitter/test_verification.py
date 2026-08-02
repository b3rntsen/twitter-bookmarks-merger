"""Tests for the verified-completeness watermark."""
import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from twitter.models import BookmarkSyncSchedule, Tweet, TwitterProfile
from twitter.verification import (
    PAGE_SIZE, advance_watermark, bounded_fetch_may_have_truncated, needs_full_rebuild,
    pages_needed, plan_fetch, verify_bookmarks, verify_for,
)

BASE = timezone.now() - timedelta(days=30)


class WatermarkTestCase(TestCase):
    """Builds a throwaway birdmarks cache + master dir on disk per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache = self.tmp / 'cache'
        self.assets = self.cache / 'assets'
        self.media = self.tmp / 'media'
        self.master = self.tmp / 'master'
        for d in (self.assets, self.media, self.master):
            d.mkdir(parents=True)

        user = User.objects.create_user('t', 't@example.com', 'pw')
        self.profile = TwitterProfile.objects.create(
            user=user, twitter_username='tester', encrypted_credentials='')
        self.schedule = BookmarkSyncSchedule.objects.create(
            twitter_profile=self.profile, use_until_synced=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- fixture helpers -------------------------------------------------

    def add_tweet(self, tweet_id, minutes, *, text='hello', media=(),
                  cached=True, assets_present=True, served=True,
                  exported=True, categorised=True):
        """Create one bookmark and the on-disk artefacts implied by the flags."""
        tweet = Tweet.objects.create(
            twitter_profile=self.profile, tweet_id=tweet_id,
            author_username='a', text_content=text, created_at=BASE)
        # scraped_at is auto_now_add, so pin it after the fact.
        scraped = BASE + timedelta(minutes=minutes)
        Tweet.objects.filter(pk=tweet.pk).update(scraped_at=scraped)

        if cached:
            body = ''.join(f'![](assets/{name})\n' for name in media)
            (self.cache / f'{tweet_id}.md').write_text(
                f'---\nid: "{tweet_id}"\nauthor: a\ndate: 2026-01-01\n---\n\n{text}\n{body}',
                encoding='utf-8')
        for name in media:
            if assets_present:
                (self.assets / name).write_text('x' * 10, encoding='utf-8')
            if served:
                (self.media / tweet_id).mkdir(parents=True, exist_ok=True)
                (self.media / tweet_id / name).write_text('x' * 10, encoding='utf-8')

        self._exported = getattr(self, '_exported', [])
        self._categorised = getattr(self, '_categorised', [])
        if exported:
            self._exported.append(tweet_id)
        if categorised:
            self._categorised.append(tweet_id)
        self.write_master()
        return scraped

    def write_master(self):
        (self.master / 'bookmarks.json').write_text(
            json.dumps([{'Tweet Id': t} for t in getattr(self, '_exported', [])]),
            encoding='utf-8')
        (self.master / 'categories.json').write_text(
            json.dumps({'tweet_categories': {t: ['x'] for t in getattr(self, '_categorised', [])}}),
            encoding='utf-8')

    def verify(self, ignored_ids=None):
        return verify_bookmarks(cache_dir=self.cache, media_dir=self.media,
                                master_dir=self.master, ignored_ids=ignored_ids)

    # --- watermark placement ---------------------------------------------

    def test_all_complete_watermark_is_newest_ingest(self):
        self.add_tweet('1', 0, media=['a.jpg'])
        self.add_tweet('2', 10)
        newest = self.add_tweet('3', 20, media=['b.jpg'])

        report = self.verify()

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.checked, 3)
        self.assertEqual(report.verified, 3)
        self.assertEqual(report.above_watermark, 0)
        self.assertEqual(report.fetch_gaps, [])

    def test_missing_asset_holds_watermark_below_the_gap(self):
        self.add_tweet('1', 0, media=['a.jpg'])
        oldest_ok = self.add_tweet('2', 10)
        self.add_tweet('3', 20, media=['gone.jpg'], assets_present=False)
        self.add_tweet('4', 30)

        report = self.verify()

        # Watermark sits at the last good ingest *strictly before* the gap, so a
        # re-fetch is forced to walk back far enough to repair it.
        self.assertEqual(report.watermark, oldest_ok)
        self.assertEqual(report.verified, 2)
        self.assertEqual(report.above_watermark, 2)
        self.assertEqual(len(report.fetch_gaps), 1)
        self.assertEqual(report.fetch_gaps[0]['tweet_id'], '3')
        self.assertIn('missing_asset', report.fetch_gaps[0]['reasons'])

    def test_gap_on_oldest_bookmark_yields_no_watermark(self):
        self.add_tweet('1', 0, media=['gone.jpg'], assets_present=False)
        self.add_tweet('2', 10)

        report = self.verify()

        self.assertIsNone(report.watermark)
        self.assertEqual(report.verified, 0)

    def test_local_gaps_do_not_hold_the_watermark_back(self):
        # Uncategorised / unexported / unserved media are repaired locally by the
        # sync pipeline; re-fetching from Twitter would not fix them, so they must
        # not force the fetcher to walk deeper.
        self.add_tweet('1', 0, media=['a.jpg'], served=False)
        newest = self.add_tweet('2', 10, categorised=False, exported=False)

        report = self.verify()

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.fetch_gaps, [])
        self.assertEqual(report.local_gaps.get('media_not_served'), 1)
        self.assertEqual(report.local_gaps.get('not_categorised'), 1)
        self.assertEqual(report.local_gaps.get('not_exported'), 1)

    def test_legacy_tweet_without_cache_is_not_a_gap(self):
        # Pre-birdmarks bookmarks (imported from the Chrome extension exports)
        # have no markdown. The DB row is the durable record; the cache is
        # disposable, so their absence must not pin the watermark at zero.
        self.add_tweet('1', 0, cached=False)
        newest = self.add_tweet('2', 10)

        report = self.verify()

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.legacy_no_cache, 1)
        self.assertEqual(report.fetch_gaps, [])

    def test_legacy_tweet_with_no_content_is_a_gap(self):
        self.add_tweet('1', 0, cached=False, text='   ')

        report = self.verify()

        self.assertIsNone(report.watermark)
        self.assertEqual(len(report.fetch_gaps), 1)
        self.assertIn('empty_content', report.fetch_gaps[0]['reasons'])

    def test_media_only_tweet_with_blank_text_is_not_a_gap(self):
        # A tweet that is just an image has no text by nature. Every blank row in
        # the production archive was this, so treating blankness alone as a defect
        # would have pinned the watermark on perfectly healthy bookmarks.
        self.add_tweet('1', 0, text='', media=['pic.jpg'])
        newest = self.add_tweet('2', 10)

        report = self.verify()

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.fetch_gaps, [])
        self.assertNotIn('content_not_imported', report.local_gaps)

    def test_cached_but_unimported_content_is_a_local_gap(self):
        # Markdown is cached, so the text is recoverable by re-importing; that is
        # local repair, not a re-fetch, and must not block.
        self.add_tweet('1', 0, text='')
        newest = self.add_tweet('2', 10)

        report = self.verify()

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.fetch_gaps, [])
        self.assertEqual(report.local_gaps.get('content_not_imported'), 1)

    # --- quarantine -------------------------------------------------------

    def test_quarantined_gap_releases_the_watermark(self):
        # A deleted tweet can never be re-fetched. Left unquarantined it pins the
        # watermark at its ingest time forever, which is what defeats the bound.
        self.add_tweet('1', 0)
        self.add_tweet('dead', 10, cached=False, text='')
        newest = self.add_tweet('3', 20)

        blocked = self.verify()
        self.assertEqual(len(blocked.fetch_gaps), 1)
        self.assertLess(blocked.watermark, newest)

        released = self.verify(ignored_ids=['dead'])
        self.assertEqual(released.watermark, newest)
        self.assertEqual(released.fetch_gaps, [])
        self.assertEqual(len(released.ignored_gaps), 1)
        self.assertEqual(released.ignored_gaps[0]['tweet_id'], 'dead')

    def test_quarantine_does_not_hide_new_gaps(self):
        self.add_tweet('dead', 0, cached=False, text='')
        self.add_tweet('broken', 10, media=['gone.jpg'], assets_present=False)

        report = self.verify(ignored_ids=['dead'])

        self.assertEqual(len(report.ignored_gaps), 1)
        self.assertEqual(len(report.fetch_gaps), 1)
        self.assertEqual(report.fetch_gaps[0]['tweet_id'], 'broken')

    def test_verify_for_reads_the_quarantine_off_the_schedule(self):
        # The path both the sync task and the admin action use. Reading the
        # quarantine from anywhere else silently re-blocks on excluded records.
        self.add_tweet('dead', 0, cached=False, text='')
        newest = self.add_tweet('2', 10)
        self.schedule.verification_ignored_ids = ['dead']

        report = verify_for(self.schedule, cache_dir=self.cache, media_dir=self.media,
                            master_dir=self.master)

        self.assertEqual(report.watermark, newest)
        self.assertEqual(report.fetch_gaps, [])
        self.assertEqual(len(report.ignored_gaps), 1)

    def test_missing_verification_report_does_not_crash_planning(self):
        self.add_tweet('1', 0)
        advance_watermark(self.schedule, self.verify())
        self.schedule.last_full_rebuild_at = timezone.now()
        self.schedule.verification_report = None

        self.assertFalse(needs_full_rebuild(self.schedule)[0])

    # --- burst guard ------------------------------------------------------

    def test_burst_filling_the_margin_forces_a_full_rebuild(self):
        bounded = {'full_rebuild': False}
        margin_capacity = self.schedule.fetch_margin_pages * PAGE_SIZE

        self.assertFalse(bounded_fetch_may_have_truncated(self.schedule, bounded, 1))
        self.assertFalse(
            bounded_fetch_may_have_truncated(self.schedule, bounded, margin_capacity - 1))
        self.assertTrue(
            bounded_fetch_may_have_truncated(self.schedule, bounded, margin_capacity))

    def test_full_rebuild_never_counts_as_truncated(self):
        self.assertFalse(
            bounded_fetch_may_have_truncated(self.schedule, {'full_rebuild': True}, 10_000))

    # --- persistence ------------------------------------------------------

    def test_advance_watermark_persists_and_reports_change(self):
        newest = self.add_tweet('1', 0)
        report = self.verify()

        self.assertTrue(advance_watermark(self.schedule, report))
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.verified_ok_before, newest)
        self.assertEqual(self.schedule.verified_count, 1)
        self.assertIsNotNone(self.schedule.verified_at)

        # Re-running with an unchanged result reports no movement.
        self.assertFalse(advance_watermark(self.schedule, self.verify()))

    def test_report_caps_stored_gap_sample(self):
        for i in range(60):
            self.add_tweet(str(i), i, media=['x%d.jpg' % i], assets_present=False)
        stored = self.verify().as_dict()

        self.assertEqual(len(stored['fetch_gaps']), 50)
        self.assertEqual(stored['fetch_gap_count'], 60)

    # --- fetch planning ---------------------------------------------------

    def test_pages_needed_covers_unverified_region_plus_margin(self):
        for i in range(45):
            self.add_tweet(str(i), i)
        report = self.verify()
        advance_watermark(self.schedule, report)

        # Everything verified: only the margin is needed.
        self.assertEqual(pages_needed(self.schedule), self.schedule.fetch_margin_pages)

        # Pull the watermark back behind 45 bookmarks -> 3 pages of 20, + margin.
        self.schedule.verified_ok_before = BASE - timedelta(minutes=1)
        self.assertEqual(pages_needed(self.schedule), 3 + self.schedule.fetch_margin_pages)

    def test_plan_is_bounded_once_a_watermark_exists(self):
        self.add_tweet('1', 0)
        advance_watermark(self.schedule, self.verify())
        self.schedule.last_full_rebuild_at = timezone.now()

        plan = plan_fetch(self.schedule)

        self.assertFalse(plan['full_rebuild'])
        self.assertIn('--max-pages', plan['args'])
        self.assertTrue(plan['clear_state'])

    def test_plan_is_unbounded_without_a_watermark(self):
        plan = plan_fetch(self.schedule)

        self.assertTrue(plan['full_rebuild'])
        self.assertEqual(plan['args'], ['--rebuild'])
        self.assertNotIn('--max-pages', plan['args'])

    def test_plan_is_unbounded_while_fetch_gaps_remain(self):
        self.add_tweet('1', 0)
        self.add_tweet('2', 10, media=['gone.jpg'], assets_present=False)
        advance_watermark(self.schedule, self.verify())
        self.schedule.last_full_rebuild_at = timezone.now()

        full, why = needs_full_rebuild(self.schedule)

        self.assertTrue(full)
        self.assertEqual(why, 'unrepaired fetch gaps')

    def test_stale_full_rebuild_forces_an_unbounded_walk(self):
        self.add_tweet('1', 0)
        advance_watermark(self.schedule, self.verify())

        self.schedule.last_full_rebuild_at = timezone.now() - timedelta(days=3)
        self.assertFalse(needs_full_rebuild(self.schedule)[0])

        self.schedule.last_full_rebuild_at = timezone.now() - timedelta(days=8)
        self.assertTrue(needs_full_rebuild(self.schedule)[0])

        # interval 0 disables the periodic walk entirely
        self.schedule.full_rebuild_interval_days = 0
        self.assertFalse(needs_full_rebuild(self.schedule)[0])

    # --- management command -----------------------------------------------

    def run_command(self, *args):
        """Run verify_bookmarks with the command's paths pointed at the fixtures."""
        out = StringIO()
        with mock.patch('twitter.verification.BIRDMARKS_CACHE', self.cache), \
             mock.patch('twitter.verification.BOOKMARKS_MEDIA_DIR', self.media), \
             mock.patch('twitter.verification.MASTER_DIR', self.master):
            call_command('verify_bookmarks', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_command_reports_without_writing(self):
        self.add_tweet('1', 0)

        output = self.run_command()

        self.assertIn('watermark', output)
        self.assertIn('dry run', output)
        self.schedule.refresh_from_db()
        self.assertIsNone(self.schedule.verified_ok_before)

    def test_command_advance_persists(self):
        newest = self.add_tweet('1', 0)

        self.run_command('--advance')

        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.verified_ok_before, newest)

    def test_command_quarantine_gaps_releases_and_advances(self):
        self.add_tweet('dead', 0, cached=False, text='')
        newest = self.add_tweet('2', 10)

        output = self.run_command('--quarantine-gaps')

        self.assertIn('Quarantined 1', output)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.verification_ignored_ids, ['dead'])
        # --quarantine-gaps implies --advance, so the released watermark is stored.
        self.assertEqual(self.schedule.verified_ok_before, newest)

    def test_command_clear_quarantine_rechecks(self):
        self.add_tweet('dead', 0, cached=False, text='')
        self.add_tweet('2', 10)
        self.run_command('--quarantine-gaps')

        output = self.run_command('--clear-quarantine')

        self.assertIn('Cleared 1', output)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.verification_ignored_ids, [])

    def test_command_json_output_is_parseable(self):
        self.add_tweet('1', 0)

        payload = json.loads(self.run_command('--json').split('\n\n')[0])

        self.assertEqual(payload['checked'], 1)
        self.assertIn('watermark', payload)

    def test_fixed_window_mode_is_untouched(self):
        self.schedule.use_until_synced = False
        self.schedule.max_pages = 4

        plan = plan_fetch(self.schedule)

        self.assertEqual(plan['args'], ['--max-pages', '4'])
        self.assertFalse(plan['clear_state'])
        self.assertFalse(plan['full_rebuild'])
