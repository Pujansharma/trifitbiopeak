import json
from datetime import date

from django.db.models import Model

from accounts.users.models import User
from programs.models import Program, ProgramAuditLog


def create_program_audit_log(
    program: Program,
    changed_field: str,
    previous_value: object,
    current_value: object,
    created_by: User | None,
) -> None:
    if previous_value == current_value:
        return

    values = []
    for value in (previous_value, current_value):
        if isinstance(value, Model):
            value = value.pk
        if isinstance(value, date):
            value = value.isoformat()
        if isinstance(value, (bool, list)):
            value = json.dumps(value)
        values.append(None if value is None else f"{value}")

    ProgramAuditLog.objects.create(
        program=program,
        changed_field=changed_field,
        previous_value=values[0],
        current_value=values[1],
        created_by=created_by,
    )
