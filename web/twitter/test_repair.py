"""Tests for repairing bookmarks that were imported with empty text."""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from twitter.models import Tweet, TwitterProfile
from twitter.tasks import repair_unimported_content


class RepairUnimportedContentTest(TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        user = User.objects.create_user('t', 't@example.com', 'pw')
        self.profile = TwitterProfile.objects.create(
            user=user, twitter_username='tester', encrypted_credentials='')

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def make_tweet(self, tweet_id, text='', author='', display=''):
        return Tweet.objects.create(
            twitter_profile=self.profile, tweet_id=tweet_id,
            author_username=author, author_display_name=display,
            text_content=text, created_at=timezone.now())

    def write_md(self, name, tweet_id, text, author='alice', author_name='Alice'):
        (self.cache / name).write_text(
            f'---\nid: "{tweet_id}"\nauthor: {author}\nauthor_name: "{author_name}"\n'
            f'date: 2026-01-01\n---\n\n# Thread\n\n**@{author}** ({author_name})\n2026-01-01\n\n{text}\n',
            encoding='utf-8')

    def test_blank_row_is_refilled_from_cache(self):
        tweet = self.make_tweet('123')
        self.write_md('2026-01-01-alice-123.md', '123', 'the recovered text')

        self.assertEqual(repair_unimported_content(self.cache), 1)

        tweet.refresh_from_db()
        self.assertIn('the recovered text', tweet.text_content)
        self.assertEqual(tweet.author_username, 'alice')
        self.assertEqual(tweet.author_display_name, 'Alice')

    def test_whitespace_only_row_counts_as_blank(self):
        tweet = self.make_tweet('123', text='   \n  ')
        self.write_md('2026-01-01-alice-123.md', '123', 'recovered')

        self.assertEqual(repair_unimported_content(self.cache), 1)

        tweet.refresh_from_db()
        self.assertIn('recovered', tweet.text_content)

    def test_plain_tweet_id_filename_is_found(self):
        tweet = self.make_tweet('123')
        self.write_md('123.md', '123', 'recovered')

        self.assertEqual(repair_unimported_content(self.cache), 1)

        tweet.refresh_from_db()
        self.assertIn('recovered', tweet.text_content)

    def test_existing_text_is_never_overwritten(self):
        tweet = self.make_tweet('123', text='original text', author='bob', display='Bob')
        self.write_md('2026-01-01-alice-123.md', '123', 'DIFFERENT text')

        self.assertEqual(repair_unimported_content(self.cache), 0)

        tweet.refresh_from_db()
        self.assertEqual(tweet.text_content, 'original text')
        self.assertEqual(tweet.author_username, 'bob')

    def test_existing_author_is_preserved_while_text_is_filled(self):
        tweet = self.make_tweet('123', author='bob', display='Bob')
        self.write_md('2026-01-01-alice-123.md', '123', 'recovered')

        repair_unimported_content(self.cache)

        tweet.refresh_from_db()
        self.assertIn('recovered', tweet.text_content)
        self.assertEqual(tweet.author_username, 'bob')
        self.assertEqual(tweet.author_display_name, 'Bob')

    def test_blank_row_without_cache_is_left_alone(self):
        # The unrepairable case — this is what quarantine exists for.
        tweet = self.make_tweet('404')

        self.assertEqual(repair_unimported_content(self.cache), 0)

        tweet.refresh_from_db()
        self.assertEqual(tweet.text_content, '')

    def test_media_only_tweet_is_not_counted_as_repaired(self):
        # Legitimately textless: markdown holds only an image reference.
        self.make_tweet('123')
        self.write_md('2026-01-01-alice-123.md', '123', '![](assets/pic.jpg)')

        # Either the extractor yields nothing (no repair) or it yields the image
        # markup; what must not happen is a silent claim of success on empty text.
        repaired = repair_unimported_content(self.cache)
        tweet = Tweet.objects.get(tweet_id='123')
        if repaired == 0:
            self.assertEqual(tweet.text_content, '')
        else:
            self.assertTrue(tweet.text_content.strip())

    def test_limit_caps_work_per_cycle(self):
        for i in range(5):
            self.make_tweet(str(i))
            self.write_md(f'{i}.md', str(i), f'text {i}')

        self.assertEqual(repair_unimported_content(self.cache, limit=2), 2)
        self.assertEqual(repair_unimported_content(self.cache, limit=99), 3)

    def test_unreadable_markdown_does_not_abort_the_batch(self):
        self.make_tweet('1')
        (self.cache / '1.md').write_bytes(b'\xff\xfe invalid utf8')
        self.make_tweet('2')
        self.write_md('2.md', '2', 'recovered')

        self.assertEqual(repair_unimported_content(self.cache), 1)
        self.assertIn('recovered', Tweet.objects.get(tweet_id='2').text_content)
