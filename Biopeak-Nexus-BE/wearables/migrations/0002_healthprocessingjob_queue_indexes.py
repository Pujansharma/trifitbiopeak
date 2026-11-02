"""Composite indexes for bounded profile freshness and provider recovery sweeps."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wearables", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="healthprocessingjob",
            index=models.Index(
                fields=["customer_profile", "job_type", "scheduled_at"],
                name="w_hjob_profile_type_s_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="healthprocessingjob",
            index=models.Index(
                fields=["connection", "job_type", "created_at"],
                name="w_hjob_conn_type_c_idx",
            ),
        ),
    ]
