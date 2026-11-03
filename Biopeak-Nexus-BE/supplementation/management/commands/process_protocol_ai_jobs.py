from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from supplementation.utils.protocol_ai import (
    UUID_TEXT_PATTERN,
    process_pending_protocol_ai_jobs,
)


class Command(BaseCommand):
    help = "Process one protocol AI recommendation job."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Max protocol AI jobs to process when --job-id is omitted.",
        )
        parser.add_argument(
            "--job-id",
            default="",
            help="Process this job only.",
        )

    def handle(self, *args, **options):
        job_id = self.job_id_from_option(options["job_id"])
        results = process_pending_protocol_ai_jobs(
            limit=options["limit"],
            job_id=job_id,
        )
        processed = len([job_id for job_id in results if job_id is not None])
        self.stdout.write(
            self.style.SUCCESS(f"Processed {processed} protocol AI job(s).")
        )

    def job_id_from_option(self, job_id_text: str):
        stripped_job_id = job_id_text.strip()
        if not stripped_job_id:
            return None
        if UUID_TEXT_PATTERN.fullmatch(stripped_job_id) is None:
            raise CommandError("Invalid job id.")
        return UUID(stripped_job_id)
