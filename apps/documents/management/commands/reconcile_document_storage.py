import argparse
from datetime import timedelta
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.documents.reconciliation import reconcile_document_storage


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if isinstance(value, bool) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


class Command(BaseCommand):
    help = "Reconcile document database state with controlled staging and final storage."

    def add_arguments(self, parser):
        parser.add_argument("--stale-seconds", type=positive_integer)
        parser.add_argument("--task-id", type=UUID)

    def handle(self, *args, **options):
        stale_seconds = options.get("stale_seconds")
        try:
            report = reconcile_document_storage(
                stale_after=(
                    timedelta(seconds=stale_seconds) if stale_seconds is not None else None
                ),
                task_id=options.get("task_id"),
            )
        except Exception as exc:
            raise CommandError(f"Document storage reconciliation failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Reconciliation task: {report.task_id}"))
        self.stdout.write(
            " ".join(
                (
                    f"checked={report.checked_assets}",
                    f"resumed={report.resumed_uploads}",
                    f"quarantined={report.quarantined_uploads}",
                    f"missing={report.marked_missing}",
                    f"restored={report.restored_missing}",
                    f"staging_cleaned={report.cleaned_staging}",
                    f"orphan_final={len(report.orphan_final_keys)}",
                    f"failures={len(report.failures)}",
                )
            )
        )
        for key in report.orphan_final_keys:
            self.stdout.write(self.style.WARNING(f"orphan final (reported only): {key}"))
        for failure in report.failures:
            self.stderr.write(self.style.ERROR(failure))
