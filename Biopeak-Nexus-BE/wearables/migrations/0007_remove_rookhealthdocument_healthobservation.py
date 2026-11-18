# Stage 2: remove the two obsolete tables. Run after 0006 has backfilled all data.
#
# The foreign-key columns are removed first, so dropping the document table cannot
# cascade into RookOutbox or RookWebhookReceipt rows. Receipts and outbox jobs keep
# every row; only their now-unused link to a document is removed.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("wearables", "0006_rook_receipts_daily_contributions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="rookoutbox",
            name="document",
        ),
        migrations.RemoveField(
            model_name="rookwebhookreceipt",
            name="document",
        ),
        migrations.DeleteModel(
            name="HealthObservation",
        ),
        migrations.DeleteModel(
            name="RookHealthDocument",
        ),
    ]
