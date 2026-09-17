"""Create the starter plans and flags a new deployment needs.

Idempotent: safe to run on every deploy. It only fills gaps — an existing plan
is never rewritten, because the price someone is already paying is not
something a deploy script should be allowed to change.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from staffportal.models import FeatureFlag, Plan
from staffportal.services.subscriptions import ensure_subscription

PLANS = [
    {
        "slug": "free",
        "name": "Free",
        "tagline": "Try it on a couple of postings.",
        "price_cents": 0,
        "sort_order": 10,
        "is_default": True,
        "max_profiles": 1,
        "monthly_job_analyses": 5,
        "monthly_tailored_resumes": 2,
        "monthly_resume_imports": 1,
        "features": "1 profile\n5 job analyses a month\n2 tailored resumes a month",
    },
    {
        "slug": "pro",
        "name": "Pro",
        "tagline": "For an active search.",
        "price_cents": 1200,
        "sort_order": 20,
        "max_profiles": 5,
        "monthly_job_analyses": 100,
        "monthly_tailored_resumes": 50,
        "monthly_resume_imports": 20,
        "features": "5 profiles\n100 job analyses a month\n50 tailored resumes a month\nPDF export",
    },
    {
        "slug": "unlimited",
        "name": "Unlimited",
        "tagline": "No ceilings.",
        "price_cents": 2900,
        "sort_order": 30,
        "max_profiles": None,
        "monthly_job_analyses": None,
        "monthly_tailored_resumes": None,
        "monthly_resume_imports": None,
        "features": "Unlimited profiles\nUnlimited analyses\nUnlimited resumes\nPriority support",
    },
]

FLAGS = [
    {
        "key": "pricing-page",
        "name": "Public pricing page",
        "description": "Shows plans and prices to signed-out visitors.",
        "state": FeatureFlag.OFF,
    },
    {
        "key": "usage-meter",
        "name": "Usage meter in the app",
        "description": "Shows customers how much of this month's allowance they have used.",
        "state": FeatureFlag.STAFF,
    },
]


class Command(BaseCommand):
    help = "Seed starter plans and feature flags, and back-fill subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="Also put existing accounts with no subscription on the default plan.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        verbose = options.get("verbosity", 1)

        def say(message, style=None):
            if verbose:
                self.stdout.write(style(message) if style else message)

        for spec in PLANS:
            plan, created = Plan.objects.get_or_create(
                slug=spec["slug"], defaults={k: v for k, v in spec.items() if k != "slug"}
            )
            say(f"{'created' if created else 'kept'} plan: {plan.name}")

        for spec in FLAGS:
            flag, created = FeatureFlag.objects.get_or_create(
                key=spec["key"], defaults={k: v for k, v in spec.items() if k != "key"}
            )
            say(f"{'created' if created else 'kept'} flag: {flag.key}")

        if options["backfill"]:
            from django.contrib.auth import get_user_model

            count = 0
            for user in get_user_model().objects.filter(subscription__isnull=True):
                if ensure_subscription(user):
                    count += 1
            say(f"Back-filled {count} subscription(s).", self.style.SUCCESS)

        say("Done.", self.style.SUCCESS)
