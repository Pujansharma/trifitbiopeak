# Phase 1 additive migration: new profile/organization wearables feature choice.
# This is a choices-only AlterField; it does not rewrite existing rows.
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0019_remove_customerprofile_emergency_contact_name_and_more")]
    operations = [
        migrations.AlterField(
            model_name="customerprofilefeature",
            name="enabled_tabs",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(choices=[('reports', 'Reports'), ('analysis', 'Analysis'), ('action_plan', 'Action Plan'), ('care_team', 'Care Team'), ('personalised_plan', 'Personalised Guidebook'), ('wellness', 'Wellness'), ('wearables', 'Wearables')]),
                blank=True,
                default=list,
                help_text="List of tabs visible to profiles in this organization.",
            ),
        ),
    ]
