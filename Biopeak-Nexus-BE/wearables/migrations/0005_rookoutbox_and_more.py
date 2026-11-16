# Rename HealthProcessingJob → RookOutbox (preserve rows), drop lease + deadline fields.

import django.db.models.deletion
from django.db import migrations, models


def delete_midnight_scheduler_jobs(apps, schema_editor):
    RookOutbox = apps.get_model("wearables", "RookOutbox")
    RookOutbox.objects.filter(job_type="daily_midnight_rook_sync").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0027_merge_20261116_0335"),
        ("wearables", "0004_remove_healthprocessingjob_uniq_rook_running_recovery_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="HealthProcessingJob",
            new_name="RookOutbox",
        ),
        migrations.RunPython(delete_midnight_scheduler_jobs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="rookoutbox",
            name="job_type",
            field=models.CharField(
                choices=[
                    ("authorise_rook_connection", "Authorise Rook connection"),
                    ("revoke_rook_connection", "Revoke Rook connection"),
                    ("fetch_rook_data", "Fetch Rook data"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="rookoutbox",
            name="connection",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rook_outboxes",
                to="wearables.wearableconnection",
            ),
        ),
        migrations.AlterField(
            model_name="rookoutbox",
            name="customer_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rook_outboxes",
                to="customers.customerprofile",
            ),
        ),
        migrations.AlterField(
            model_name="rookoutbox",
            name="document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rook_outboxes",
                to="wearables.rookhealthdocument",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="rookoutbox",
            name="uniq_rook_running_recovery",
        ),
        migrations.AddConstraint(
            model_name="rookoutbox",
            constraint=models.UniqueConstraint(
                condition=models.Q(("job_type", "fetch_rook_data"), ("status", "running")),
                fields=("connection",),
                name="uniq_rook_running_fetch",
            ),
        ),
        migrations.RemoveField(
            model_name="rookoutbox",
            name="deadline_at",
        ),
        migrations.RemoveField(
            model_name="rookoutbox",
            name="worker_run_id",
        ),
        migrations.DeleteModel(
            name="RookWorkerLease",
        ),
    ]
