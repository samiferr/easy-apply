"""Create the starter plans and flags a new deployment needs (UC-08.5, UC-08.6).

Idempotent: safe to run on every deploy. It only fills gaps — an existing plan
is never rewritten, because the price someone is already paying is not
something a deploy script should be allowed to change. The plans and flags are
`STARTER_PLANS` and `STARTER_FLAGS` in `staffportal/services.py`.
"""

from django.core.management.base import BaseCommand

from staffportal import services


class Command(BaseCommand):
    help = "Seed starter plans and feature flags, and back-fill subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="Also put existing accounts with no subscription on the default plan.",
        )

    def handle(self, *args, **options):
        verbose = options.get("verbosity", 1)

        def say(message, style=None):
            if verbose:
                self.stdout.write(style(message) if style else message)

        seeded = services.seed_starter_data(backfill=options["backfill"])

        for plan, created in seeded["plans"]:
            say(f"{'created' if created else 'kept'} plan: {plan.name}")
        for flag, created in seeded["flags"]:
            say(f"{'created' if created else 'kept'} flag: {flag.key}")
        if options["backfill"]:
            say(f"Back-filled {seeded['backfilled']} subscription(s).", self.style.SUCCESS)

        say("Done.", self.style.SUCCESS)
