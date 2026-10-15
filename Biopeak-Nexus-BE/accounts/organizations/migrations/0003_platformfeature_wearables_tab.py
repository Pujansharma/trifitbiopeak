# Feature-choice state migration only; adds no new database columns.
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_platformfeature"),
    ]

    operations = [
        migrations.AlterField(
            model_name="platformfeature",
            name="enabled_tabs",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(
                    choices=[
                        ("reports", "Reports"),
                        ("analysis", "Analysis"),
                        ("action_plan", "Action Plan"),
                        ("care_team", "Care Team"),
                        ("personalised_plan", "Personalised Guidebook"),
                        ("wellness", "Wellness"),
                        ("wearables", "Wearables"),
                    ]
                ),
                blank=True,
                default=list,
                help_text="List of tabs visible to profiles in this organization.",
            ),
        ),
    ]
