from argparse import ArgumentParser

from django import forms
from django.core.management.base import BaseCommand, CommandError

from programs.models import TherapyProgramService
from programs.utils.constants import ProgramType


class BackfillCutoffForm(forms.Form):
    created_before = forms.DateTimeField()


class Command(BaseCommand):
    help = "Initialize legacy therapy service centers from stored program selections before deployment."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--created-before", required=True)

    def handle(self, *args, **options) -> None:
        cutoff_form = BackfillCutoffForm({"created_before": options["created_before"]})
        if not cutoff_form.is_valid():
            raise CommandError("Provide a valid ISO 8601 --created-before timestamp.")
        services = (
            TherapyProgramService.objects.filter(
                created_at__lt=cutoff_form.cleaned_data["created_before"],
                program_service__program__program_type=ProgramType.THERAPY,
                redeemable_centers__isnull=True,
            )
            .select_related("program_service__program")
            .prefetch_related("program_service__program__redeemable_centers")
        )
        initialized_count = 0
        assignment_model = TherapyProgramService.redeemable_centers.through
        for therapy_service in services.iterator(chunk_size=200):
            centers = list(
                therapy_service.program_service.program.redeemable_centers.all()
            )
            if not centers:
                continue
            assignment_model.objects.bulk_create(
                [
                    assignment_model(
                        therapyprogramservice=therapy_service, center=center
                    )
                    for center in centers
                ],
                ignore_conflicts=True,
            )
            initialized_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Initialized centers for {initialized_count} service lines."
            )
        )
