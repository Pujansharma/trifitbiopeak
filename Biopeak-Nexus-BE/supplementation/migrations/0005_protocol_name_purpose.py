from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def copy_protocol_identity(apps, schema_editor):
    Protocol = apps.get_model("supplementation", "Protocol")
    ProtocolVersion = apps.get_model("supplementation", "ProtocolVersion")
    first_version = ProtocolVersion.objects.filter(protocol_id=OuterRef("pk")).order_by(
        "version_number"
    )
    Protocol.objects.update(
        name=Subquery(first_version.values("name")[:1]),
        purpose=Subquery(first_version.values("purpose")[:1]),
    )
    Protocol.objects.filter(name__isnull=True).update(name="", purpose="")


class Migration(migrations.Migration):

    dependencies = [
        ("supplementation", "0004_protocolitem"),
    ]

    operations = [
        migrations.AddField(
            model_name="protocol",
            name="name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="protocol",
            name="purpose",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(copy_protocol_identity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="protocol",
            name="name",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="protocol",
            name="purpose",
            field=models.TextField(),
        ),
        migrations.RemoveField(
            model_name="protocolversion",
            name="name",
        ),
        migrations.RemoveField(
            model_name="protocolversion",
            name="purpose",
        ),
    ]
