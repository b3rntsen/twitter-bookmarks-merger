"""Verified-completeness watermark for bookmark syncing.

The fetcher (birdmarks) walks bookmarks newest-first. Without a stopping rule it
re-walks the entire collection on every run, so run time grows with the archive
and nearly all the work is re-fetching content we already hold.

This module establishes a watermark: a timestamp ``T`` such that *every bookmark
ingested at or before T is verified complete*. Everything at or below T never
needs fetching again, so a run only has to cover the region above T plus a
safety margin for bookmarks added since the last run.

Axis choice
-----------
The watermark is on ``Tweet.scraped_at`` (when we first ingested the bookmark),
not ``Tweet.created_at`` (when the tweet was written). Twitter paginates
bookmarks in *bookmark-added* order, and a freshly bookmarked five-year-old
tweet appears on page 1. ``created_at`` therefore says nothing about pagination
position, while ``scraped_at`` is monotonic in the order we saw things and is a
sound proxy for "how deep in the list this sits".

Two tiers of completeness
-------------------------
``fetch``-blocking gaps are things only a re-fetch from Twitter can fix (missing
DB row, missing cached asset). They hold the watermark back.

``local`` gaps are things the existing pipeline repairs on its own each cycle
(media not yet copied to the served media dir, tweet not yet categorised, not
yet in bookmarks.json). They are reported but do *not* hold the watermark back,
because re-fetching from Twitter would not fix them.

Known limit
-----------
No local check can discover a bookmark that exists on Twitter but was never
fetched — that is only observable by fetching. The safety margin and the
periodic full rebuild (see ``plan_fetch``) exist to cover that case.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from math import ceil
from pathlib import Path

from django.utils import timezone

from .models import Tweet

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'tools'))
from markdown_parser import parse_frontmatter, extract_media_filenames  # noqa: E402

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
MASTER_DIR = _ROOT / 'master'
BIRDMARKS_CACHE = _ROOT / 'birdmarks_cache'
BOOKMARKS_MEDIA_DIR = Path(os.environ.get('BOOKMARKS_MEDIA_DIR', str(MASTER_DIR / 'media')))

# Twitter's bookmark timeline returns 20 entries per page. Deliberately
# conservative: underestimating page size only makes us fetch more pages than
# strictly needed, which is safe. Overestimating would skip bookmarks.
PAGE_SIZE = 20

# Gap kinds that only a re-fetch can repair. Anything else is local repair.
FETCH_BLOCKING = {'missing_asset', 'empty_content'}


@dataclass
class VerificationReport:
    """Outcome of one verification pass."""

    watermark: object = None  # datetime | None
    checked: int = 0
    verified: int = 0
    above_watermark: int = 0
    fetch_gaps: list = field(default_factory=list)
    ignored_gaps: list = field(default_factory=list)
    local_gaps: dict = field(default_factory=dict)
    legacy_no_cache: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            'watermark': self.watermark.isoformat() if self.watermark else None,
            'checked': self.checked,
            'verified': self.verified,
            'above_watermark': self.above_watermark,
            # Cap the stored sample: a systemic breakage must not write a
            # multi-megabyte blob into the schedule row.
            'fetch_gaps': self.fetch_gaps[:50],
            'fetch_gap_count': len(self.fetch_gaps),
            'ignored_gaps': self.ignored_gaps[:50],
            'ignored_gap_count': len(self.ignored_gaps),
            'local_gaps': self.local_gaps,
            'legacy_no_cache': self.legacy_no_cache,
            'duration_seconds': round(self.duration_seconds, 2),
        }

    def summary(self) -> str:
        wm = self.watermark.isoformat() if self.watermark else 'none'
        local = ', '.join(f'{k}={v}' for k, v in sorted(self.local_gaps.items())) or 'none'
        ignored = f", {len(self.ignored_gaps)} quarantined" if self.ignored_gaps else ''
        return (
            f"verified {self.verified}/{self.checked} complete through {wm} "
            f"({self.above_watermark} above watermark, "
            f"{len(self.fetch_gaps)} fetch gaps{ignored}, local gaps: {local})"
        )


def _build_cache_index(cache_dir: Path) -> dict:
    """Map tweet_id -> list of media filenames referenced by its cached markdown."""
    index = {}
    if not cache_dir.exists():
        return index
    for md_file in cache_dir.glob('*.md'):
        try:
            frontmatter, body = parse_frontmatter(md_file.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"verification: unreadable cache file {md_file.name}: {e}")
            continue
        tweet_id = str(frontmatter.get('id', ''))
        if tweet_id:
            index[tweet_id] = extract_media_filenames(body)
    return index


def _scandir_names(path: Path) -> set:
    """Names of non-empty files directly under path. Empty set if absent."""
    if not path.exists():
        return set()
    names = set()
    with os.scandir(path) as entries:
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_size > 0:
                    names.add(entry.name)
            except OSError:
                continue
    return names


def _load_ids(path: Path, extract) -> set:
    if not path.exists():
        return set()
    try:
        with open(path, encoding='utf-8') as f:
            return extract(json.load(f))
    except Exception as e:
        logger.warning(f"verification: could not read {path.name}: {e}")
        return set()


def verify_bookmarks(cache_dir: Path = None, media_dir: Path = None,
                     master_dir: Path = None, ignored_ids=None) -> VerificationReport:
    """Check every known bookmark and compute the verified-complete watermark.

    ``ignored_ids`` quarantines bookmarks whose gaps no re-fetch can repair (a
    deleted tweet, a truncated legacy import). They are still reported, but they
    do not hold the watermark back — otherwise a single dead record from years
    ago pins the watermark there permanently and the bound never pays off.

    Returns a report; does not write anything. Call ``advance_watermark`` to
    persist the result onto a schedule.
    """
    started = timezone.now()
    ignored_ids = {str(i) for i in (ignored_ids or ())}
    cache_dir = cache_dir or BIRDMARKS_CACHE
    media_dir = media_dir or BOOKMARKS_MEDIA_DIR
    master_dir = master_dir or MASTER_DIR

    cache_index = _build_cache_index(cache_dir)
    assets = _scandir_names(cache_dir / 'assets')
    exported_ids = _load_ids(
        master_dir / 'bookmarks.json',
        lambda d: {str(b.get('Tweet Id')) for b in d},
    )
    categorised_ids = _load_ids(
        master_dir / 'categories.json',
        lambda d: {str(k) for k in d.get('tweet_categories', {})},
    )

    report = VerificationReport()
    local_gaps = {}
    # Watermark boundary: scraped_at of the earliest fetch-blocking gap. The
    # watermark must land strictly below it.
    first_blocking_at = None

    tweets = (
        Tweet.objects
        .filter(is_bookmark=True)
        .order_by('scraped_at', 'id')
        .values('id', 'tweet_id', 'scraped_at', 'text_content')
        .iterator(chunk_size=500)
    )

    rows = []
    for row in tweets:
        report.checked += 1
        tweet_id = str(row['tweet_id'])
        scraped_at = row['scraped_at']
        rows.append((scraped_at, tweet_id))

        blocking = []
        local = []

        has_content = bool((row['text_content'] or '').strip())
        media_files = cache_index.get(tweet_id)
        if media_files is None:
            # No cached markdown. The DB row is the durable record and the cache
            # is disposable, so this alone is not a gap — but a row with no
            # content and no cache is unrecoverable without a re-fetch.
            report.legacy_no_cache += 1
            if not has_content:
                blocking.append('empty_content')
        else:
            missing_assets = [f for f in media_files if f not in assets]
            if missing_assets:
                blocking.append('missing_asset')
            # Media staged in cache but not yet copied to the served media dir.
            if media_files and not missing_assets:
                served = _scandir_names(media_dir / tweet_id)
                if any(f not in served for f in media_files):
                    local.append('media_not_served')
            # Cached markdown exists but the DB row is empty: the import dropped
            # the text. Re-importing fixes it locally, so this does not block.
            if not has_content and not media_files:
                local.append('content_not_imported')

        if tweet_id not in exported_ids:
            local.append('not_exported')
        if tweet_id not in categorised_ids:
            local.append('not_categorised')

        for kind in local:
            local_gaps[kind] = local_gaps.get(kind, 0) + 1

        if blocking:
            gap = {
                'tweet_id': tweet_id,
                'scraped_at': scraped_at.isoformat() if scraped_at else None,
                'reasons': blocking,
            }
            if tweet_id in ignored_ids:
                report.ignored_gaps.append(gap)
            else:
                report.fetch_gaps.append(gap)
                if scraped_at and (first_blocking_at is None or scraped_at < first_blocking_at):
                    first_blocking_at = scraped_at

    report.local_gaps = local_gaps

    # The watermark is the latest scraped_at strictly below the earliest
    # fetch-blocking gap. With no gaps it is the newest ingest we hold.
    if first_blocking_at is None:
        report.watermark = max((s for s, _ in rows if s), default=None)
    else:
        below = [s for s, _ in rows if s and s < first_blocking_at]
        report.watermark = max(below, default=None)

    if report.watermark:
        report.above_watermark = sum(1 for s, _ in rows if s and s > report.watermark)
        report.verified = sum(1 for s, _ in rows if s and s <= report.watermark)

    report.duration_seconds = (timezone.now() - started).total_seconds()
    return report


def verify_for(schedule, **kwargs) -> VerificationReport:
    """Verify, honouring the quarantine list stored on a schedule."""
    return verify_bookmarks(ignored_ids=schedule.verification_ignored_ids or [], **kwargs)


def bounded_fetch_may_have_truncated(schedule, plan: dict, imported: int) -> bool:
    """Whether a bounded run might have stopped short of the newest bookmarks.

    A bounded walk covers the unverified region plus a fixed margin. If a run
    imported as many bookmarks as the margin holds, the burst may have been
    larger than the window and the top of the list may extend past where we
    stopped. The caller answers this by forcing an unbounded walk next run.
    """
    if plan.get('full_rebuild'):
        return False
    return imported >= max(1, schedule.fetch_margin_pages) * PAGE_SIZE


def advance_watermark(schedule, report: VerificationReport) -> bool:
    """Persist a verification result onto a schedule.

    The watermark only ever moves forward from a verification pass; a pass that
    finds a new gap deeper in the archive legitimately moves it *back*, which is
    what widens the next fetch. Returns True if the stored value changed.
    """
    previous = schedule.verified_ok_before
    schedule.verified_ok_before = report.watermark
    schedule.verified_at = timezone.now()
    schedule.verified_count = report.verified
    schedule.verification_report = report.as_dict()
    schedule.save(update_fields=[
        'verified_ok_before', 'verified_at', 'verified_count',
        'verification_report', 'updated_at',
    ])
    if previous != report.watermark:
        logger.info(f"verification: watermark {previous} -> {report.watermark}")
        return True
    return False


def pages_needed(schedule, page_size: int = PAGE_SIZE) -> int:
    """Pages the next fetch must cover to reach verified territory.

    Bookmarks ingested after the watermark still sit above it in the timeline,
    so the fetch has to walk at least that far, plus a margin for bookmarks
    added since the last run (which no local check can count).
    """
    watermark = schedule.verified_ok_before
    margin = max(1, schedule.fetch_margin_pages)
    if watermark is None:
        return 0  # 0 == unbounded; caller decides
    unverified = Tweet.objects.filter(is_bookmark=True, scraped_at__gt=watermark).count()
    return ceil(unverified / page_size) + margin


def needs_full_rebuild(schedule) -> tuple:
    """Whether the next run must ignore the watermark bound, and why.

    A bounded fetch cannot see bookmarks that were never ingested, nor detect
    ones removed on Twitter. A periodic unbounded walk is the backstop.
    """
    if not schedule.verified_ok_before:
        return True, 'no watermark established yet'
    if (schedule.verification_report or {}).get('fetch_gap_count'):
        return True, 'unrepaired fetch gaps'
    interval = schedule.full_rebuild_interval_days
    if interval <= 0:
        return False, ''
    last = schedule.last_full_rebuild_at
    if last is None:
        return True, 'no full rebuild on record'
    age = timezone.now() - last
    if age >= timedelta(days=interval):
        return True, f'last full rebuild {age.days}d ago (interval {interval}d)'
    return False, ''


def plan_fetch(schedule) -> dict:
    """Decide the birdmarks arguments for the next run.

    birdmarks has no timestamp option, so the watermark is translated into a
    page bound: ``--rebuild`` always starts at page 1 (newest), and
    ``--max-pages`` stops it once it has covered the unverified region.
    """
    if not schedule.use_until_synced:
        return {
            'args': ['--max-pages', str(schedule.max_pages)],
            'full_rebuild': False,
            'clear_state': False,
            'reason': f'fixed window: {schedule.max_pages} pages',
        }

    full, why = needs_full_rebuild(schedule)
    if full:
        return {
            'args': ['--rebuild'],
            'full_rebuild': True,
            'clear_state': True,
            'reason': f'full rebuild: {why}',
        }

    pages = pages_needed(schedule)
    return {
        'args': ['--rebuild', '--max-pages', str(pages)],
        'full_rebuild': False,
        'clear_state': True,
        'reason': (
            f'bounded to {pages} pages by watermark '
            f'{schedule.verified_ok_before.isoformat()}'
        ),
    }
