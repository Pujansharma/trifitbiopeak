"""Unify Biopeak client migrations with the previously released wearable choice.

A merge migration contains no database operations. Keep both branches intact
because older environments may already have applied the wearable 0020.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0022_merge_20261012_1150"),
        ("customers", "0020_customerprofilefeature_wearables_feature_choice"),
    ]
    operations = []
