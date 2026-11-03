from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("supplementation", "0005_protocol_name_purpose"),
    ]

    operations = [
        migrations.RenameField(
            model_name="protocolversion",
            old_name="summary",
            new_name="summary_notes",
        ),
    ]
