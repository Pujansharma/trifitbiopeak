from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("supplementation", "0012_protocol_ai_outbox"),
        ("integrations", "0017_protocolaioutbox"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="ProtocolAiOutbox"),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='DROP TABLE IF EXISTS "supplementation_protocolaioutbox" CASCADE;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
