"""Report — and optionally advance — the verified-completeness watermark.

Read-only by default so it is safe to run against production at any time:

    python manage.py verify_bookmarks              # report only
    python manage.py verify_bookmarks --advance    # persist the watermark
    python manage.py verify_bookmarks --json       # machine-readable
"""
import json

from django.core.management.base import BaseCommand

from twitter.models import BookmarkSyncSchedule
from twitter.verification import (
    advance_watermark, needs_full_rebuild, pages_needed, plan_fetch, verify_for,
)


class Command(BaseCommand):
    help = "Verify bookmark completeness and report the sync watermark"

    def add_arguments(self, parser):
        parser.add_argument('--advance', action='store_true',
                            help='Persist the computed watermark onto the schedule')
        parser.add_argument('--json', action='store_true',
                            help='Emit the report as JSON')
        parser.add_argument('--show-gaps', type=int, default=10,
                            help='How many fetch gaps to list (default 10)')
        parser.add_argument('--quarantine-gaps', action='store_true',
                            help='Mark every current fetch gap as unrepairable so it stops '
                                 'holding the watermark back (implies --advance)')
        parser.add_argument('--clear-quarantine', action='store_true',
                            help='Empty the quarantine list and re-check those bookmarks')

    def handle(self, *args, **options):
        schedule = BookmarkSyncSchedule.objects.first()
        if schedule is None:
            self.stderr.write(self.style.ERROR('No sync schedule configured.'))
            return

        if options['clear_quarantine']:
            count = len(schedule.verification_ignored_ids or [])
            schedule.verification_ignored_ids = []
            schedule.save(update_fields=['verification_ignored_ids', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(f'Cleared {count} quarantined bookmark(s).'))

        report = verify_for(schedule)

        if options['quarantine_gaps'] and report.fetch_gaps:
            quarantined = list(schedule.verification_ignored_ids or [])
            for gap in report.fetch_gaps:
                if gap['tweet_id'] not in quarantined:
                    quarantined.append(gap['tweet_id'])
            schedule.verification_ignored_ids = quarantined
            schedule.save(update_fields=['verification_ignored_ids', 'updated_at'])
            self.stdout.write(self.style.WARNING(
                f'Quarantined {len(report.fetch_gaps)} unrepairable bookmark(s); '
                f'{len(quarantined)} total.'))
            # Re-verify so the watermark reflects the quarantine.
            report = verify_for(schedule)
            options['advance'] = True

        if options['json']:
            self.stdout.write(json.dumps(report.as_dict(), indent=2))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING('Bookmark verification'))
            wm = report.watermark.isoformat() if report.watermark else 'none'
            self.stdout.write(f"  watermark (verified OK before): {wm}")
            self.stdout.write(f"  bookmarks checked:              {report.checked}")
            self.stdout.write(f"  verified complete:              {report.verified}")
            self.stdout.write(f"  above watermark (unverified):   {report.above_watermark}")
            self.stdout.write(f"  no cached markdown (legacy):    {report.legacy_no_cache}")
            self.stdout.write(f"  took:                           {report.duration_seconds:.1f}s")

            self.stdout.write('')
            if report.fetch_gaps:
                self.stdout.write(self.style.WARNING(
                    f"  {len(report.fetch_gaps)} fetch-blocking gaps (need a re-fetch):"))
                for gap in report.fetch_gaps[:options['show_gaps']]:
                    self.stdout.write(
                        f"    {gap['tweet_id']}  {gap['scraped_at']}  {','.join(gap['reasons'])}")
            else:
                self.stdout.write(self.style.SUCCESS('  no fetch-blocking gaps'))

            if report.ignored_gaps:
                self.stdout.write(
                    f"  {len(report.ignored_gaps)} quarantined (unrepairable, "
                    f"not holding the watermark back)")

            if report.local_gaps:
                self.stdout.write('  local gaps (pipeline repairs these itself):')
                for kind, count in sorted(report.local_gaps.items()):
                    self.stdout.write(f"    {kind}: {count}")

        if options['advance']:
            changed = advance_watermark(schedule, report)
            self.stdout.write(self.style.SUCCESS(
                f"\nWatermark {'updated' if changed else 'unchanged'}: {schedule.verified_ok_before}"))
        elif not options['json']:
            self.stdout.write('\n  (dry run — pass --advance to persist)')

        if not options['json']:
            # Show the effect on the next fetch using the *stored* watermark, so a
            # dry run reports what would happen today rather than after advancing.
            full, why = needs_full_rebuild(schedule)
            plan = plan_fetch(schedule)
            self.stdout.write(self.style.MIGRATE_HEADING('\nNext fetch'))
            self.stdout.write(f"  plan:  birdmarks {' '.join(plan['args'])}")
            self.stdout.write(f"  why:   {plan['reason']}")
            if not full and schedule.verified_ok_before:
                self.stdout.write(
                    f"  pages: {pages_needed(schedule)} "
                    f"(margin {schedule.fetch_margin_pages})")
