import os
import time

from django.core.management.base import BaseCommand, CommandError

from coach.enclosure_rules import rule_for
from coach.models import EnclosureChar, ExplanationCache
from coach.views import PRACTICE_POOL, SHARED_CACHE_USER, shared_why


class Command(BaseCommand):
    help = "Pre-generate shared Gemini explanations for the practice characters. Run once before a demo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="delete shared explanations and regenerate them")
        parser.add_argument("--delay", type=float, default=2.5, help="seconds between Gemini calls")

    def handle(self, *args, **options):
        if not os.environ.get("GEMINI_API_KEY"):
            raise CommandError("Set GEMINI_API_KEY in this PowerShell window first.")
        if options["force"]:
            ExplanationCache.objects.filter(user=SHARED_CACHE_USER).delete()
        jobs = []
        for row in EnclosureChar.objects.filter(character__in=PRACTICE_POOL).order_by("character"):
            data = {"family": row.family, "frame_component": row.frame_component, "pattern": row.pattern}
            n = len(row.pattern)
            rules = {rule_for(data, e, d) for e in range(n) for d in range(e + 1, n)} - {""}
            jobs.extend((row, rule) for rule in sorted(rules))
        done = 0
        for i, (row, rule) in enumerate(jobs, 1):
            text, source = shared_why(row.character, rule, row)
            if source == "gemini":
                done += 1
                time.sleep(options["delay"])
            self.stdout.write("{}/{} {} {} -> {}".format(i, len(jobs), row.character, rule, source or "FAILED (will use fallback text)"))
        self.stdout.write(self.style.SUCCESS("Done. {} new Gemini explanations, {} total jobs.".format(done, len(jobs))))
