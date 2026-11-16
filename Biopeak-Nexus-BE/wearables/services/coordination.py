"""Serialize short ROOK mutations with ORM conditional updates, not raw SQL.

Call inside an explicit transaction. UPDATE holds its database write lock until
commit; lock order is ROOK identity -> connection -> document/job. No provider
HTTP call belongs inside these sections. No customer/appointment rows change.
"""
from django.db import transaction
from django.db.models import F
from wearables.models import RookMemberIdentity, WearableConnection


def require_atomic_block():
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("ROOK coordination requires an explicit atomic transaction.")


def serialize_profile_changes(customer_profile_id):
    require_atomic_block()
    return RookMemberIdentity.objects.filter(customer_profile_id=customer_profile_id).update(
        updated_at=F("updated_at"),
    )


def serialize_connection_changes(connection_id):
    require_atomic_block()
    changed = WearableConnection.objects.filter(pk=connection_id).update(updated_at=F("updated_at"))
    if not changed:
        raise WearableConnection.DoesNotExist("Wearable connection no longer exists.")
    return WearableConnection.objects.select_related("identity", "customer_profile").filter(pk=connection_id).first()
