import argparse

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.projects.services import expire_access_grants


def positive_integer(value: str) -> int:
    if isinstance(value, bool):
        raise argparse.ArgumentTypeError("must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


class Command(BaseCommand):
    help = "Persist expired project access grants and their audit records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=positive_integer,
            help=(
                "Validate a future batch size. The current service still processes all eligible "
                "grants in one transaction."
            ),
        )

    def handle(self, *args, **options):
        batch_size = options.get("batch_size")
        if batch_size is not None:
            try:
                batch_size = positive_integer(batch_size)
            except argparse.ArgumentTypeError as exc:
                raise CommandError("--batch-size must be a positive integer.") from exc

        try:
            expired_count = expire_access_grants()
        except ValidationError as exc:
            raise CommandError(f"Project access expiration failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Expired {expired_count} project access grant(s)."))
        if batch_size is not None:
            self.stdout.write(
                self.style.WARNING(
                    f"--batch-size={batch_size} was validated; the current service processed all "
                    "eligible grants in one transaction."
                )
            )
