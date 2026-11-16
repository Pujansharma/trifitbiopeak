import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0016_googlecalendaroutbox_and_more"),
        ("supplementation", "0012_protocol_ai_outbox"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProtocolAiOutbox",
            fields=[
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Designates whether this is marked as active",
                        verbose_name="active status",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="Designates when this object was created.",
                        verbose_name="created at",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Designates when this object was last updated.",
                        verbose_name="updated at",
                    ),
                ),
                (
                    "id",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("sending", "Sending"),
                            ("accepted", "Accepted"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("error_detail", models.TextField(blank=True, default="")),
                (
                    "skip_reason",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                (
                    "job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outbox",
                        to="supplementation.protocolaijob",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["status", "created_at"],
                        name="integration_status_aiout_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "status__in",
                                [
                                    "pending",
                                    "queued",
                                    "sending",
                                    "accepted",
                                    "failed",
                                    "skipped",
                                ],
                            )
                        ),
                        name="ai_outbox_status_valid",
                    )
                ],
            },
        ),
    ]
