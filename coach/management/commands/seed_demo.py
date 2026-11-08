from django.core.management.base import BaseCommand

from coach.models import Attempt, StrokeMistake


class Command(BaseCommand):
    help = "Create repeatable demo history for the close-the-door-last coaching rule."

    samples = (
        ("日", 3, "order_3_4"),
        ("田", 4, "order_4_5"),
        ("国", 3, "order_3_8"),
    )

    def handle(self, *args, **options):
        created = 0
        for character, stroke, diagnosis in self.samples:
            exists = StrokeMistake.objects.filter(
                user="demo", character=character, rule="close_the_door_last"
            ).exists()
            if exists:
                continue
            attempt = Attempt.objects.create(
                user="demo", character=character, mistakes=1, completed=True
            )
            StrokeMistake.objects.create(
                attempt=attempt, user="demo", character=character,
                stroke_num=stroke, diagnosis=diagnosis, rule="close_the_door_last",
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(
            "Demo history ready: {} new sample mistake(s).".format(created)
        ))
